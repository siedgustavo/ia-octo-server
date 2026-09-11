// Expert activation profiler para GLM-5-Next (glm5next) sobre llama.cpp.
// Reemplaza al ejemplo eval-callback: intercepta el tensor "ffn_moe_topk-<il>"
// (IDs de expertos seleccionados por token, I32) durante el prefill y acumula
// un histograma por (capa, experto). Al terminar, vuelca JSON a stdout y a
// /tmp/expert_profile.json para analizar el sesgo de activacion.
//
// Uso tipico (CPU-only, no toca GPUs):
//   llama-eval-callback -m GLM....gguf -ngl 0 -c 8192 -b 2048 --no-warmup \
//     -f prompt.txt
#include "arg.h"
#include "common.h"
#include "log.h"
#include "llama.h"
#include "ggml.h"
#include "ggml-backend.h"

#include <clocale>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <map>
#include <string>
#include <vector>
#include <algorithm>

struct prof_data {
    // counts[layer] -> vector indexado por expert_id
    std::map<int, std::vector<long long>> counts;
    long long total_selected = 0; // total de (token x expert_used) observados
    long long tokens_seen = 0;    // suma de n_tokens por invocacion (aprox)
};

static bool prof_cb_eval(struct ggml_tensor * t, bool ask, void * user_data) {
    auto * pd = (prof_data *) user_data;
    const char * name = t->name;
    if (std::strncmp(name, "ffn_moe_topk", 12) != 0) {
        return false; // no nos interesa este nodo
    }
    if (ask) {
        return true;  // si: observalo despues de computar
    }
    if (t->type != GGML_TYPE_I32) {
        return true;
    }
    int il = -1;
    const char * dash = std::strrchr(name, '-');
    if (dash) il = atoi(dash + 1);

    // ffn_moe_topk suele ser un view NO contiguo (top-k sobre el argsort de
    // n_expert): ne[0]=n_expert_used, ne[1]=n_tokens, pero nb[1] puede
    // corresponder a la fila completa (n_expert). Copiamos ggml_nbytes bytes
    // crudos y luego indexamos con los strides reales (nb) para no leer basura.
    const size_t nbytes = ggml_nbytes(t);
    std::vector<uint8_t> raw(nbytes);
    ggml_backend_tensor_get(t, raw.data(), 0, nbytes);

    const int64_t ne0 = t->ne[0]; // n_expert_used
    const int64_t ne1 = t->ne[1]; // n_tokens
    const size_t  nb0 = t->nb[0];
    const size_t  nb1 = t->nb[1];

    auto & vec = pd->counts[il];
    for (int64_t it = 0; it < ne1; ++it) {
        for (int64_t k = 0; k < ne0; ++k) {
            const size_t off = (size_t) it * nb1 + (size_t) k * nb0;
            if (off + sizeof(int32_t) > nbytes) continue;
            int32_t e;
            std::memcpy(&e, raw.data() + off, sizeof(int32_t));
            if (e < 0) continue;
            if ((int) vec.size() <= e) vec.resize(e + 1, 0);
            vec[e]++;
            pd->total_selected++;
        }
    }
    pd->tokens_seen += ne1;
    return true;
}

static void dump_json(const prof_data & pd, const char * path) {
    FILE * f = fopen(path, "w");
    if (!f) { LOG_ERR("no pude abrir %s\n", path); return; }
    fprintf(f, "{\n  \"total_selected\": %lld,\n  \"layers\": {\n", pd.total_selected);
    bool first_layer = true;
    for (const auto & kv : pd.counts) {
        if (!first_layer) fprintf(f, ",\n");
        first_layer = false;
        fprintf(f, "    \"%d\": [", kv.first);
        for (size_t e = 0; e < kv.second.size(); ++e) {
            if (e) fprintf(f, ",");
            fprintf(f, "%lld", kv.second[e]);
        }
        fprintf(f, "]");
    }
    fprintf(f, "\n  }\n}\n");
    fclose(f);
    LOG_INF("expert-profiler: JSON escrito en %s\n", path);
}

static void print_summary(const prof_data & pd) {
    LOG_INF("\n=== expert-profiler: resumen de sesgo por capa ===\n");
    LOG_INF("total (token x expert_used) observados: %lld\n", pd.total_selected);
    LOG_INF("layer  n_exp  used   max%%   top8%%  gini\n");
    for (const auto & kv : pd.counts) {
        const auto & v = kv.second;
        long long sum = 0, mx = 0, used = 0;
        for (auto c : v) { sum += c; if (c > mx) mx = c; if (c > 0) used++; }
        if (sum == 0) continue;
        std::vector<long long> s(v.begin(), v.end());
        std::sort(s.begin(), s.end(), std::greater<long long>());
        long long top8 = 0;
        for (size_t i = 0; i < s.size() && i < 8; ++i) top8 += s[i];
        // Gini
        std::sort(s.begin(), s.end());
        double n = s.size();
        double cum = 0, wsum = 0;
        for (size_t i = 0; i < s.size(); ++i) { cum += s[i]; wsum += cum; }
        double gini = 0.0;
        if (sum > 0 && n > 0) gini = (n + 1 - 2.0 * (wsum / sum)) / n;
        LOG_INF("%5d  %5zu  %4lld  %5.1f  %5.1f  %.3f\n",
                kv.first, v.size(), used,
                100.0 * mx / sum, 100.0 * top8 / sum, gini);
    }
}

static bool run(llama_context * ctx, const common_params & params) {
    const llama_model * model = llama_get_model(ctx);
    const llama_vocab * vocab = llama_model_get_vocab(model);
    const bool add_bos = llama_vocab_get_add_bos(vocab);

    std::vector<llama_token> tokens = common_tokenize(ctx, params.prompt, add_bos, true);
    if (tokens.empty()) {
        LOG_ERR("%s: sin tokens de entrada (usa -p o -f)\n", __func__);
        return false;
    }
    LOG_INF("expert-profiler: %zu tokens de prompt a procesar\n", tokens.size());

    // Prefill en chunks del batch para no exceder n_batch.
    const int n_batch = params.n_batch;
    for (size_t i = 0; i < tokens.size(); i += n_batch) {
        const int n = std::min<size_t>(n_batch, tokens.size() - i);
        if (llama_decode(ctx, llama_batch_get_one(tokens.data() + i, n))) {
            LOG_ERR("%s: fallo en llama_decode\n", __func__);
            return false;
        }
    }
    return true;
}

int main(int argc, char ** argv) {
    std::setlocale(LC_NUMERIC, "C");

    prof_data pd;
    common_params params;
    common_init();

    if (!common_params_parse(argc, argv, params, LLAMA_EXAMPLE_COMMON)) {
        return 1;
    }

    llama_backend_init();
    llama_numa_init(params.numa);

    params.cb_eval = prof_cb_eval;
    params.cb_eval_user_data = &pd;
    params.warmup = false;

    auto llama_init = common_init_from_params(params);
    auto * model = llama_init->model();
    auto * ctx   = llama_init->context();
    if (model == nullptr || ctx == nullptr) {
        LOG_ERR("%s: fallo al inicializar\n", __func__);
        return 1;
    }

    LOG_INF("\n%s\n\n", common_params_get_system_info(params).c_str());

    bool OK = run(ctx, params);
    if (!OK) return 1;

    print_summary(pd);
    dump_json(pd, "/tmp/expert_profile.json");

    LOG("\n");
    llama_perf_context_print(ctx);
    llama_backend_free();
    return 0;
}
