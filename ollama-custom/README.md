# Ollama (retirado)

Ollama se saco del octoserver el 2026-11-19: container, imagenes y `/opt/ollama` borrados, y el servicio
quitado de `docker-compose.yml`. Los modelos estan archivados en inference2
(`docs/ollama-store-archive.md`).

Este directorio (patches + `Dockerfile`) y los Modelfiles de `../ollama/` quedan como receta. Para volver:
recuperar el servicio `ollama` de `docker-compose.yml` del commit anterior a su retiro
(`git log -S "octofan-ollama" -- docker-compose.yml`), traer el store desde inference2 y nunca levantarlo
junto a Strata/Maya (las mismas GPU).
