#!/usr/bin/env bash

#Must be empty in release
DEBUG_COMMANDS=

################################################################################
# Firmware info
FIRMWARE_UPDATE_LOG="/hive/opt/octofan/fw_update.log"
FW_VERSION_07="1.1"
FW_VERSION_09="1.6"
FW_FILENAME_07="/hive/opt/octofan/firmware_07.hex"
FW_FILENAME_09="/hive/opt/octofan/firmware_09.hex"
FIRMWARE_MD5_07="46392f7827d482586768afb34ca02322"
FIRMWARE_MD5_09="4b39fb3797d6c956d44284c6e71defd6"
MAINTENANCE_SEM_NAME="/tmp/octofan_fw_update"
################################################################################

if [[ -z $OCTOFAN_CONF ]]; then #reread env variables as after upgrade this can be empty
  source /etc/environment
  export $(cat /etc/environment | grep -vE '^$|^#' | cut -d= -f1) #export all variables from file
fi

. colors
. /hive-config/rig.conf

export DISPLAY=":0"

DEF_SLEEP_TIME=10

OCTOFAN_BIN="/hive/opt/octofan/fan_controller_cli"
CLI_OUTPUT="/tmp/fan_controller_cli_output"
CLI_ERROR_COUNTER="/tmp/octofan_cli_error_count"
CLI_TMP_OUTPUT="/tmp/octofan_cli_temp.txt"
OCTOFAN_PERCENT_PWM="/hive/opt/octofan/octofan_percent_pwm"
PSU_LAST_POWER_FILENAME="/tmp/octofan_psu_last_power"

CLI_LOG_BASE_NAME="/var/log/hive-octofan-cli" #without .log
CLI_LOGS_BASE_DIR=/var/log/
MAX_LOG_SIZE=10000000 #10m

CALC_AVERAGE_SPEED=1

################################################################################
#settings (for octofan.conf without DEF_), default values
#fan LEDs 0-orange, 1-blue, 2-white
#blink on errors
DEF_BLINK_ON_ERRORS=1
#LED number for blink on errors
DEF_BLINK_ON_ERRORS_LED=0
#blink type on errors: 0=off, 1=on, 2=blink 0.1s, 3=blink 1s, >=4=blink 3s
DEF_BLINK_ON_ERRORS_TYPE=2
#blink type on warnings: 0=off, 1=on, 2=blink 0.1s, 3=blink 1s, >=4=blink 3s
DEF_BLINK_ON_WARNINGS_TYPE=3
#blink off type: 0=off, 1=on, 2=blink 0.1s, 3=blink 1s, >=4=blink 3s
DEF_BLINK_OFF_TYPE=0
#blink to find the rig in rack
DEF_BLINK_TO_FIND=0
#LED number for blink to find the rig in rack
DEF_BLINK_TO_FIND_LED=2
#blink type to find the rig in rack: 0=off, 1=on, 2=blink 0.1s, 3=blink 1s, >=4=blink 3s
DEF_BLINK_TO_FIND_TYPE=1
#manual fan speed
DEF_MANUAL_FAN=100
#enabled auto fan control
DEF_AUTO_ENABLED=1
#minimal fan speed
DEF_MIN_FAN=30
#maximum fan speed
DEF_MAX_FAN=100

DEF_FAN_PWN_FACTOR=-30

DEF_TARGET_TEMP=66
DEF_TARGET_MEM_TEMP=90
DEF_TEMP_VARIATION=0
DEF_FAN_INC_SPEED_STEP=5
#######################################################################
BLINK_ON_ERRORS=
BLINK_TO_FIND=
MANUAL_FAN=
AUTO_ENABLED=
MIN_FAN=
MAX_FAN=

BLINK_ON_ERRORS_LED=
BLINK_ON_ERRORS_TYPE=
BLINK_ON_WARNINGS_TYPE=
BLINK_OFF_TYPE=
BLINK_TO_FIND_LED=
BLINK_TO_FIND_TYPE=

FAN_ARRAY=()

FAN_PWN_FACTORS=()

FAN_INC_SPEED_FACTORS=()

TARGET_TEMP=
TARGET_MEM_TEMP=

prev_temp_array=
prev_mtemp_array=

RECALIBRATE_TIME=70
ERROR_RPM=1000 #send error message when fan max RPM is less
WARNING_RPM=2000 #send warning message when fan max RPM is less


#######################################################################

#flag that the message was sent
unable_to_set_fan_speed=0
#unparsable data
error_in_read_configs=0

#######################################################################

save_text_to_EEPROM () {
  check_sem
  [[ $? -ne 0 ]] && return 1 #octofan in maintenance mode

  echo2 "${GREEN}Saving text to Octofan EEPROM${NOCOLOR}"
  local current_ip=`hostname -I | sed 's/ /\n/g' | head -1`
  #$OCTOFAN_BIN -o 1,0,3 -v "ROH Ultra"
  $OCTOFAN_BIN -o 0,0,4 -v 0
  local str=`print_c "$WORKER_NAME" 10`
  $OCTOFAN_BIN -o 0,0,3 -v "$str"
  $OCTOFAN_BIN -o 0,2,2 -v "IP: $current_ip"
  $OCTOFAN_BIN -o 0,3,2 -v "Algo:"
  $OCTOFAN_BIN -o 0,4,2 -v "Hashrate:"
  $OCTOFAN_BIN -o 0,5,2 -v "Power:"
  $OCTOFAN_BIN -o 0,6,2 -v "In:"
  $OCTOFAN_BIN -o 10,6,2 -v "Out:"
  $OCTOFAN_BIN -o 0,7,2 -v ""
}


update_text () {
  check_sem
  [[ $? -ne 0 ]] && return 1 #octofan in maintenance mode

  check_cli_output
  fan_autodetect

  echo2 "${GREEN}Updating Octofan OLED text${NOCOLOR}"
  local hashrate=`echo "$2*1000" | bc`
  hashrate=`shorten_hashrate $hashrate`
  power_ac=`cat $CLI_OUTPUT | grep "PSU" | grep " Pac:" | grep -v "Peak" | cut -d " " -f 6 | awk '{sum+=$1} END { printf "%.0f", sum }'`
  in_t=`cat $CLI_OUTPUT | grep "BME280 No. 0 Temp: " | cut -d " " -f 5 | awk '{print int($1)}'`
  [[ -z $in_t || $in_t == '-nan' ]] && in_t=`cat $CLI_OUTPUT | grep "Temperature No. 0" | cut -d " " -f 5 | awk '{print int($1)}'`
  out_t=`cat $CLI_OUTPUT | grep "BME280 No. 1 Temp: " | cut -d " " -f 5 | awk '{print int($1)}'`
  [[ -z $out_t || $out_t == '-nan' ]] && out_t=`cat $CLI_OUTPUT | grep "Temperature No. 1" | cut -d " " -f 5 | awk '{print int($1)}'`
  local f_speeds; local t_speed
  for (( i = 0; i < ${#FAN_ARRAY[@]}; i++ )); do
    t_speed=`cat $CLI_OUTPUT | grep "FAN No. ${FAN_ARRAY[$i]} RPM in percent:" | cut -d " " -f 7`
    [[ $t_speed -lt 100 ]] && t_speed+="%"
    f_speeds+="$t_speed "
  done
  local str=`print_l $1 14`
  $OCTOFAN_BIN -o 6,3,0 -v "$str"
  str=`print_l $hashrate 10`
  $OCTOFAN_BIN -o 10,4,0 -v "$str"
  str=`print_l "${power_ac}W" 13`
  $OCTOFAN_BIN -o 7,5,0 -v "$str"
  #In 20°C  Out 40°C
  str=`print_l "${in_t}°C" 5`
  $OCTOFAN_BIN -o 4,6,0 -v "$str"
  str=`print_l "${out_t}°C" 5`
  $OCTOFAN_BIN -o 15,6,0 -v "$str"
  #99% 99% 99% 100 100
  str=`print_l "$f_speeds" 20`
  $OCTOFAN_BIN -o 0,7,0 -v "$str"
}

function echo2 {
  echo -e "$1"
}

check_config () {
  if [ ! -f $OCTOFAN_CONF ]; then
    echo2 "${RED}No config $OCTOFAN_CONF${NOCOLOR}"
  fi
}

print_space () {
  for i in $(seq $1); do
    echo -n ' '
  done
}

print_l () {
  local length=${#1}
  if [[ $2 -gt $length ]]; then
    echo -n "$1"
    print_space $(($2 - $length))
  else
    [[ length -ne $2 ]] && echo "$1" | cut -c1-$2 || echo "$1"
  fi
}

print_r () {
  local length=${#1}
  if [[ $2 -gt $length ]]; then
    print_space $(($2 - $length))
    echo -n "$1"
  else
    [[ length -ne $2 ]] && echo "$1" | cut -c1-$2 || echo "$1"
  fi
}

print_c () {
  local length=${#1}
  if [[ $2 -gt $length ]]; then
    l_space=$((($2 - $length) / 2))
    r_space=$(($2 - $l_space - $length))
    print_space $l_space
    echo -n "$1"
    print_space $r_space
  else
    [[ length -ne $2 ]] && echo "$1" | cut -c1-$2 || echo "$1"
  fi
}

function echo2 {
  echo -e "$1"
}

check_config () {
  if [ ! -f $OCTOFAN_CONF ]; then
    echo2 "${RED}No config $OCTOFAN_CONF${NOCOLOR}"
  fi
}

shorten_hashrate () {
  if [[ $1 > 100 ]]; then
    echo $1 | numfmt --suffix="h/s" --to=si
  else
    echo $1 | numfmt --suffix="h/s" --format="%'3.3f"
  fi
}

calc_fan_speed () {
  if [[ $AUTO_ENABLED -ne 1 ]]; then
    if [[ ! -z $MANUAL_FAN ]]; then
      fan_speed=$MANUAL_FAN #showing manual value
    else
      fan_speed=100 #can't get manual value, setting fan speed to 100%
    fi
    return 0
  fi

  if [[ -z $bus_id_array ]]; then
    [[ $DEBUG_COMMANDS -ge 1 ]] && echo "check GPU_DETECT_JSON and do nothing while not exist"
    while true; do
      if [ -f $GPU_DETECT_JSON ]; then
        bus_id_array=(`cat $GPU_DETECT_JSON | jq -c '[ . | to_entries[] | select(.value) | .value.busid [0:2] ]'`)
        break
      else
        echo2 "${RED}No $GPU_DETECT_JSON file exist${NOCOLOR}"
      fi
      sleep 10
    done
  fi

  if [[ -z $fan_array ]]; then
    [[ $DEBUG_COMMANDS -ge 1 ]] && echo "check GPU_STATS_JSON and do nothing while not exist"
    while true; do
      if [ -f $GPU_STATS_JSON ]; then
        fan_array=(`cat $GPU_STATS_JSON | tail -1 | jq -c ".fan"`)
        break
      else
        echo2 "${RED}No $GPU_STATS_JSON file exist${NOCOLOR}"
      fi
      sleep 10
    done
  fi

  if [[ -z $temp_array ]]; then
    [[ $DEBUG_COMMANDS -ge 1 ]] && echo "check GPU_STATS_JSON and do nothing while not exist"
    while true; do
      if [ -f $GPU_STATS_JSON ]; then
        temp_array=(`cat $GPU_STATS_JSON | tail -1 | jq -c ".temp"`)
        break
      else
        echo2 "${RED}No $GPU_STATS_JSON file exist${NOCOLOR}"
      fi
      sleep 10
    done
  fi

  if [[ -z $mtemp_array ]]; then
    [[ $DEBUG_COMMANDS -ge 1 ]] && echo "check GPU_STATS_JSON and do nothing while not exist"
    while true; do
      if [ -f $GPU_STATS_JSON ]; then
        mtemp_array=(`cat $GPU_STATS_JSON | tail -1 | jq -c ".mtemp"`)
        break
      else
        echo2 "${RED}No $GPU_STATS_JSON file exist${NOCOLOR}"
      fi
      sleep 10
    done
  fi

  fan_speed=$MIN_FAN
  local t_bus_id=0
  local a_fan=0
  local prev_fan=0
  local s_fan=0
  local n_fan=0
  local a_temp=0
  local a_mtemp=0
  local i=0
  local a_fan_inc_speed=-2000
  local t_fan_inc_speed=-1
  local a_gpus_fan_max_count=0
  if [[ ! -z $bus_id_array && ! -z $fan_array ]]; then
    case $1 in
      0) #fan 0 blows on cards 01:00.0, 02:00.0, 03:00.0
        local first_gpu=1
        local last_gpu=3
      ;;
      1) #fan 1 blows on cards 05:00.0, 06:00.0, 07:00.0
        local first_gpu=5
        local last_gpu=7
      ;;
      2) #fan 2 blows on cards 08:00.0, 09:00.0, 0a:00.0
        local first_gpu=8
        local last_gpu=10
      ;;
      5)
        local first_gpu=1
        local last_gpu=13
    esac

    for (( i=$first_gpu; i <= $last_gpu; i++ )); do
      t_fan_inc_speed=
      t_fan_inc_speed_m=
      for ((j = 0; j < $(jq length <<< "$bus_id_array"); j++)); do
        t_bus_id=$(jq -r .[$j] <<< $bus_id_array)
        if [[ "$(( 0x${t_bus_id} ))" == "$i" ]]; then
          a_fan=$(jq -r .[$j] <<< $fan_array)
          [[ $a_fan -gt $fan_speed ]] && fan_speed=$a_fan
          [[ $a_fan -eq 0 ]] && a_fan=100 #fan broken or fanless GPU, increaseing case fan speed to cool down GPU
          ((s_fan+=$a_fan)) && ((n_fan++))

          if [[ $a_fan -eq 100 ]]; then #calc fan increase factor to compensate GPU heat. It can be negative on fanless GPUs
            ((a_gpus_fan_max_count++))
            [[ $DEBUG_COMMANDS -ge 1 ]] && echo GPU$i fan is 100%
            # calc fan speed fot core temp
            prev_temp=$(jq -r .[$j] <<< $prev_temp_array)
            if [[ ! -z $prev_temp && $prev_temp -ne 0 ]]; then
              a_temp=$(jq -r .[$j] <<< $temp_array)
              [[ $DEBUG_COMMANDS -ge 1 ]] && echo $prev_temp \=\> $a_temp
              if [[ $(($a_temp - $TARGET_TEMP)) -gt $DEF_TEMP_VARIATION ]]; then
                if [[ $a_temp -gt $prev_temp ]]; then
                  ((t_fan_inc_speed=$a_temp - $TARGET_TEMP))
                elif [[ $a_temp -lt $prev_temp ]]; then
                  t_fan_inc_speed=-1
                else
                  t_fan_inc_speed=0
                fi
              else #if [[ $a_temp -lt $TARGET_TEMP ]]; then
                if [[ $(($TARGET_TEMP - $a_temp)) -gt 3 ]]; then
                  ((t_fan_inc_speed=$a_temp - $TARGET_TEMP))
                elif [[ $a_temp -gt $prev_temp ]]; then
                  ((t_fan_inc_speed=$a_temp - $prev_temp -1))
                elif [[ $a_temp -lt $prev_temp ]]; then
                  t_fan_inc_speed=-1
                else
                  t_fan_inc_speed=0
                fi
              fi
            fi
            # calc fan speed for mem temp
            prev_mtemp=$(jq -r .[$j] <<< $prev_mtemp_array)
            if [[ ! -z $prev_mtemp && $prev_mtemp -ne 0 ]]; then
              a_mtemp=$(jq -r .[$j] <<< $mtemp_array)
              [[ $DEBUG_COMMANDS -ge 1 ]] && echo $prev_mtemp \=\> $a_mtemp
              if [[ $(($a_mtemp - $TARGET_MEM_TEMP)) -gt $DEF_TEMP_VARIATION ]]; then
                if [[ $a_mtemp -gt $prev_mtemp ]]; then
                  ((t_fan_inc_speed_m=$a_mtemp - $TARGET_MEM_TEMP))
                elif [[ $a_mtemp -lt $prev_mtemp ]]; then
                  t_fan_inc_speed_m=-1
                else
                  t_fan_inc_speed_m=0
                fi
              else #if [[ $a_temp -lt $TARGET_TEMP ]]; then
                if [[ $(($TARGET_MEM_TEMP - $a_mtemp)) -gt 3 ]]; then
                  ((t_fan_inc_speed_m=$a_mtemp - $TARGET_MEM_TEMP))
                elif [[ $a_mtemp -gt $prev_mtemp ]]; then
                  ((t_fan_inc_speed_m=$a_mtemp - $prev_mtemp -1))
                elif [[ $a_mtemp -lt $prev_mtemp ]]; then
                  t_fan_inc_speed_m=-1
                else
                  t_fan_inc_speed_m=0
                fi
              fi
            fi
            # use the biggest fan speed
            if [[ -n $t_fan_inc_speed_m ]]; then
              if [[ $t_fan_inc_speed -lt $t_fan_inc_speed_m ]]; then
                t_fan_inc_speed=$t_fan_inc_speed_m
              fi
            fi
          fi
        fi
      done
      #take max fan_inc_speed factor from cooling GPU
      [[ ! -z $t_fan_inc_speed && $a_fan_inc_speed -lt $t_fan_inc_speed ]] && a_fan_inc_speed=$t_fan_inc_speed
    done
    [[ $a_fan_inc_speed -eq -2000 ]] && a_fan_inc_speed=0

    [[ $CALC_AVERAGE_SPEED == 1 && $n_fan -gt 0 ]] && fan_speed=`expr $s_fan / $n_fan`

    # if none of gpu fan speed is 100% then set a_fan_inc_speed closer to zero
    [[ $DEBUG_COMMANDS -ge 1 ]] && echo "a_gpus_fan_max_count=$a_gpus_fan_max_count"
    if [[ $a_gpus_fan_max_count -eq 0 ]]; then
      if [[ ${FAN_INC_SPEED_FACTORS[$1]} -gt 0 ]]; then
        [[ $DEBUG_COMMANDS -ge 1 ]] && echo "All GPUs fan speed are lower than 100%. Decreasing FAN_INC_SPEED_FACTORS[$1]"
        a_fan_inc_speed=-1
      elif [[ ${FAN_INC_SPEED_FACTORS[$1]} -lt 0 ]]; then
        [[ $DEBUG_COMMANDS -ge 1 ]] && echo "All GPUs fan speed are lower than 100%. Increasing FAN_INC_SPEED_FACTORS[$1]"
        a_fan_inc_speed=1
      else
        a_fan_inc_speed=0
      fi
    fi

    #add speed factor to compensate gpu overheat
    ((FAN_INC_SPEED_FACTORS[$1]+=$a_fan_inc_speed * $DEF_FAN_INC_SPEED_STEP))
    [[ ${FAN_INC_SPEED_FACTORS[$1]} -gt 100 ]] && FAN_INC_SPEED_FACTORS[$1]=100
    [[ ${FAN_INC_SPEED_FACTORS[$1]} -lt -100 ]] && FAN_INC_SPEED_FACTORS[$1]=-100
    #[[ ${FAN_INC_SPEED_FACTORS[$1]} -lt 0 ]] && FAN_INC_SPEED_FACTORS[$1]=0
    #[[ ${FAN_INC_SPEED_FACTORS[$1]} -gt 0 ]] &&
    ((fan_speed+=${FAN_INC_SPEED_FACTORS[$1]}))

    #adding 10% to fan0 to compensate extra heat from CPU and PSU
    [[ $1 -eq 0 ]] && ((fan_speed+=10))

    [[ $fan_speed -gt $MAX_FAN ]] && fan_speed=$MAX_FAN
    [[ $fan_speed -lt $MIN_FAN ]] && fan_speed=$MIN_FAN
    [[ $fan_speed -gt 100 ]] && fan_speed=100
  else #error on getting card fan values, setting max speed
    fan_speed=$MAX_FAN
  fi
}

percent_to_pwm () {
  local pwm=
  # [[ -f $OCTOFAN_PERCENT_PWM ]] && pwm=`cat $OCTOFAN_PERCENT_PWM | grep " ${1}%" | head -1 | cut -d " " -f 4`
  if [ -z $2 ]; then
    [[ -z $pwm ]] && pwm=`echo $1 $DEF_FAN_PWN_FACTOR| awk '{ printf("%.0f\n",255*$1/100+$2) }'`
  else
    [[ -z $pwm ]] && pwm=`echo $1 ${FAN_PWN_FACTORS[$2]}| awk '{ printf("%.0f\n",255*$1/100+$2) }'`
  fi
  [[ $pwm -gt 255 ]] && pwm=255
  [[ $pwm -lt 0 ]] && pwm=0
  echo $pwm
}

set_fan_speed () {
  check_sem
  if [[ $? -eq 0 ]]; then
    local target_speed=$2
    [[ $target_speed -gt $MAX_FAN ]] && target_speed=$MAX_FAN
    [[ $target_speed -lt $MIN_FAN ]] && target_speed=$MIN_FAN
    fan_id=${FAN_ARRAY[$1]}
    local pwm=`percent_to_pwm $target_speed $1`
    echo2 "Setting FAN $1 speed to ${PURPLE}$target_speed%${NOCOLOR}, Min Fan $MIN_FAN%, Max Fan $MAX_FAN%, FAN_ID=$fan_id, PWM=$pwm"
    [[ ! -z $1 && ! -z $2 ]] && $OCTOFAN_BIN -f $fan_id -v $pwm
  fi
}

set_fans_speed () {
  check_sem
  if [[ $? -eq 0 ]]; then
    if [[ ! -z $1 ]]; then
      for (( j = 0; j < ${#FAN_ARRAY[@]}; j++ )); do
      # for j in ${#FAN_ARRAY[@]}; do
        set_fan_speed $j $1
      done
    fi
  fi
}

blink_error () {
  check_sem
  [[ $? -ne 0 ]] && return 1 #octofan in maintenance mode

  if [[ $BLINK_ON_ERRORS == 1 ]]; then
    echo2 "${RED}Blinking LED to show error state${NOCOLOR}"

    $OCTOFAN_BIN -l $BLINK_ON_ERRORS_LED -v $BLINK_ON_ERRORS_TYPE
  else
    echo2 "${GREEN}Blink on error disabled, turning off LED${NOCOLOR}"

    $OCTOFAN_BIN -l $BLINK_ON_ERRORS_LED -v $BLINK_OFF_TYPE
  fi
}

blink_warning () {
  check_sem
  [[ $? -ne 0 ]] && return 1 #octofan in maintenance mode

  if [[ $BLINK_ON_ERRORS == 1 ]]; then
    echo2 "${YELLOW}Blinking LED to show warning state${NOCOLOR}"

    $OCTOFAN_BIN -l $BLINK_ON_ERRORS_LED -v $DEF_BLINK_ON_WARNINGS_TYPE
  else
    echo2 "${GREEN}Blink on error disabled, turning off LED${NOCOLOR}"

    $OCTOFAN_BIN -l $BLINK_ON_ERRORS_LED -v $BLINK_OFF_TYPE
  fi
}

blink_off () {
  check_sem
  [[ $? -ne 0 ]] && return 1 #octofan in maintenance mode

  echo2 "${GREEN}Normal state, turning off LED${NOCOLOR}"

  $OCTOFAN_BIN -l $BLINK_ON_ERRORS_LED -v $BLINK_OFF_TYPE
}

blink_to_find () {
  check_sem
  [[ $? -ne 0 ]] && return 1 #octofan in maintenance mode

  if [[ $BLINK_TO_FIND == 1 ]]; then
    echo2 "${WHITE}Turning on LED to find the rig in rack${NOCOLOR}"

    $OCTOFAN_BIN -l $BLINK_TO_FIND_LED -v $BLINK_TO_FIND_TYPE
  else
    $OCTOFAN_BIN -l $BLINK_TO_FIND_LED -v $BLINK_OFF_TYPE
  fi
}

fan_autodetect () {
  # check_cli_output

  FAN_ARRAY=()

  if [[ -f $CLI_OUTPUT ]]; then

    local i=0
    local j=0
    local fan_id=
    local line=

    for i in {0..11}; do
      line=`cat $CLI_OUTPUT | grep "FAN No. $i max RPM:"`
      [[ `echo $line | cut -d " " -f 6` -eq 0 ]] && continue
      fan_id=`echo $line | cut -d " " -f 3`
      FAN_ARRAY[$j]=$fan_id
      ((j++))
    done
    [[ ${#FAN_ARRAY[@]} -gt 3 ]] && AUTOFAN_SYNCHRO_MODE=1 #override for x12ultra rigs
  fi

  if [[ ${#FAN_ARRAY[@]} -eq 0 ]]; then
    echo_log "$(date +"%Y-%m-%d %T")"
    echo_log "No casefans detected."
  fi
}

load_def_values () {
  [[ -f $OCTOFAN_CONF ]] && source $OCTOFAN_CONF

  [[ -z $BLINK_ON_ERRORS ]] && BLINK_ON_ERRORS=$DEF_BLINK_ON_ERRORS
  [[ -z $BLINK_TO_FIND ]] && BLINK_TO_FIND=$DEF_BLINK_TO_FIND
  [[ -z $MANUAL_FAN ]] && MANUAL_FAN=$DEF_MANUAL_FAN
  [[ -z $AUTO_ENABLED ]] &&AUTO_ENABLED=$DEF_AUTO_ENABLED
  [[ -z $MIN_FAN ]] && MIN_FAN=$DEF_MIN_FAN
  [[ -z $MAX_FAN ]] && MAX_FAN=$DEF_MAX_FAN
  [[ -z $TARGET_TEMP ]] && TARGET_TEMP=$DEF_TARGET_TEMP
  [[ -z $TARGET_MEM_TEMP ]] && TARGET_MEM_TEMP=$DEF_TARGET_MEM_TEMP

  [[ -z $BLINK_ON_ERRORS_LED ]] && BLINK_ON_ERRORS_LED=$DEF_BLINK_ON_ERRORS_LED
  [[ -z $BLINK_ON_ERRORS_TYPE ]] && BLINK_ON_ERRORS_TYPE=$DEF_BLINK_ON_ERRORS_TYPE
  [[ -z $BLINK_ON_WARNINGS_TYPE ]] && BLINK_ON_WARNINGS_TYPE=$DEF_BLINK_ON_WARNINGS_TYPE
  [[ -z $BLINK_OFF_TYPE ]] && BLINK_OFF_TYPE=$DEF_BLINK_OFF_TYPE
  [[ -z $BLINK_TO_FIND_LED ]] && BLINK_TO_FIND_LED=$DEF_BLINK_TO_FIND_LED
  [[ -z $BLINK_TO_FIND_TYPE ]] && BLINK_TO_FIND_TYPE=$DEF_BLINK_TO_FIND_TYPE

 [[ ${#FAN_ARRAY[@]} -eq 0 ]] && fan_autodetect

  if [[ ${#FAN_PWN_FACTORS[@]} -eq 0 ]]; then
    for (( i = 0; i < ${#FAN_ARRAY[@]}; i++ )); do
      [[ -z $FAN_PWN_FACTORS ]] && FAN_PWN_FACTORS[$i]=$DEF_FAN_PWN_FACTOR
      [[ -z $FAN_INC_SPEED_FACTORS ]] && FAN_INC_SPEED_FACTORS[$i]=0
    done
  fi
}

octo_fan_control () {
  for (( i = 0; i < ${#FAN_ARRAY[@]}; i++ )); do
    prev_fan_calc_speeds[$i]=0
  done

  #main loop
  while true;  do
    unset AUTO_ENABLED
    MIN_FAN=
    MAX_FAN=

    bus_id_array=
    fan_array=
    temp_array=
    mtemp_array=

    load_def_values
    SLEEP_TIME=$DEF_SLEEP_TIME

    echo2 "${GREEN}$(date +"%Y-%m-%d %T")${NOCOLOR}"

    while true; do
      if [ -f $GPU_DETECT_JSON ]; then
        bus_id_array=(`cat $GPU_DETECT_JSON | jq -c '[ . | to_entries[] | select(.value) | .value.busid [0:2] ]'`)
        break
      else
        echo2 "${RED}No $GPU_DETECT_JSON file exist${NOCOLOR}"
      fi
      sleep 10
    done

    while true; do
      if [ -f $GPU_STATS_JSON ]; then
        fan_array=(`cat $GPU_STATS_JSON | tail -1 | jq -c ".fan"`)
        temp_array=(`cat $GPU_STATS_JSON | tail -1 | jq -c ".temp"`)
        mtemp_array=(`cat $GPU_STATS_JSON | tail -1 | jq -c ".mtemp"`)
        break
      else
        echo2 "${RED}No $GPU_STATS_JSON file exist${NOCOLOR}"
      fi
      sleep 10
    done

    #[[ $BLINK_ON_ERRORS == 1 ]] && blink_error

    #blinking to find the rig in rack
    blink_to_find
    sleep 0.1

    calc_fan_pwm_factor

    local a_fan=0
    if [[ $AUTO_ENABLED -eq 1 ]]; then #"autofan" enabled
      if [[ $AUTOFAN_SYNCHRO_MODE -eq 1 ]]; then
        [[ $DEBUG_COMMANDS -ge 2 ]] && echo "Autofan is in synchro mode"
        #if ROH9 is in syncro mode or it's a X12ultra
        fan_speed=
        calc_fan_speed "5" #getting current fan speed value
        [[ $DEBUG_COMMANDS -ge 1 ]] && echo "FANS_INC_SPEED_FACTOR=${FAN_INC_SPEED_FACTORS[5]}"
        set_fan_speed 0 $(($fan_speed + 10)) #setting current fan speed value
        prev_fan_calc_speeds[0]=$(($fan_speed + 10))
        for (( i = 1; i < ${#FAN_ARRAY[@]}; i++ )); do
          set_fan_speed $i $fan_speed #setting current fan speed value
          prev_fan_calc_speeds[$i]=$fan_speed
        done

      else
        [[ $DEBUG_COMMANDS -ge 2 ]] && echo "Autofan is in ROH9 mode"
        for i in {0..2}; do
          fan_speed=
          calc_fan_speed $i #getting current fan speed value
          [[ $DEBUG_COMMANDS -ge 1 ]] && echo "FAN${i}_INC_SPEED_FACTOR=${FAN_INC_SPEED_FACTORS[$i]}"
          set_fan_speed $i $fan_speed #setting current fan speed value
          prev_fan_calc_speeds[$i]=$fan_speed
          sleep 0.1
        done
      fi
    else
      [[ $DEBUG_COMMANDS -ge 2 ]] && echo "Manual fan mode"
      if [[ ! -z $MANUAL_FAN ]]; then
        set_fans_speed $MANUAL_FAN #setting all fans speed to manual value
        for (( i = 0; i < ${#FAN_ARRAY[@]}; i++ )); do
          prev_fan_calc_speeds[$i]=$MANUAL_FAN
        done
        # prev_fan_calc_speeds=($MANUAL_FAN $MANUAL_FAN $MANUAL_FAN)
      else
        set_fans_speed 100 #can't get manual value, setting all fans speed to 100%
        for (( i = 0; i < ${#FAN_ARRAY[@]}; i++ )); do
          prev_fan_calc_speeds[$i]=100
        done
        # prev_fan_calc_speeds=(100 100 100)
      fi
    fi

    prev_temp_array=$temp_array
    prev_mtemp_array=$mtemp_array

    read -t $SLEEP_TIME
  done
}

calc_fan_pwm_factor () {
  check_cli_output

  for (( i = 0; i < ${#FAN_ARRAY[@]}; i++ )); do
    FAN_ID=${FAN_ARRAY[$i]}
    fan_target_speed=${prev_fan_calc_speeds[$i]}
    fan_current_speed=`cat $CLI_OUTPUT | grep "FAN No. $FAN_ID RPM in percent:" | cut -d " " -f 7`
    [[ $DEBUG_COMMANDS -ge 2 ]] && echo "FAN_ID=$FAN_ID | fan_target_speed=$fan_target_speed | fan_current_speed=$fan_current_speed"
    if [ $fan_target_speed -eq 100 ]; then
      FAN_PWN_FACTORS[$i]=0
      echo2 "Reseting FAN$i PWM factor"
    # elif [[ $fan_target_speed -gt 0 && $fan_current_speed -gt 0 ]]; then
    elif [[ $fan_target_speed -gt 0 || $fan_curent_speed -gt 0 ]]; then
      [[ $fan_current_speed -lt $fan_target_speed ]] && ((FAN_PWN_FACTORS[$i]+=$fan_target_speed-$fan_current_speed)) && echo2 "Increasing FAN$i PWM factor"
      [[ $fan_current_speed -gt $fan_target_speed ]] && ((FAN_PWN_FACTORS[$i]+=$fan_target_speed-$fan_current_speed)) && echo2 "Decreasing FAN$i PWM factor"
    fi
    [[ ${FAN_PWN_FACTORS[$i]} -lt -100 || ${FAN_PWN_FACTORS[$i]} -gt 100 ]] && FAN_PWN_FACTORS[$i]=0 && echo2 "Reseting FAN$i PWM factor"
  done

  [[ $DEBUG_COMMANDS -ge 1 ]] && echo "FAN_PWN_FACTORS: ${FAN_PWN_FACTORS[@]}"
}

get_file_time_diff () {
  local a=999
  [[ -f $CLI_OUTPUT ]] && let a=`date +%s`-`stat --format='%Y' $CLI_OUTPUT`
  echo $a
}

check_cli_output () {
  local i=0
  if [[ `get_file_time_diff` -gt 5 ]]; then
    $OCTOFAN_BIN -r > "$CLI_TMP_OUTPUT"
    if [[ `cat "$CLI_TMP_OUTPUT" | grep -c "Serial No: "` -eq 1 ]]; then
      mv "$CLI_TMP_OUTPUT" $CLI_OUTPUT >> /dev/null
      echo "" > "$CLI_ERROR_COUNTER"
    else
      echo "error getting cli output" >> "$CLI_ERROR_COUNTER"
    fi

    [[ `cat "$CLI_ERROR_COUNTER" | grep -c "error getting cli output"` -gt 50 ]] && echo "" > $CLI_OUTPUT
  fi
}

# get_temp () {
#   check_cli_output
#
#   local temp=`cat $CLI_OUTPUT | grep "Temperature No. $1" | cut -d " " -f 5`
#
#   [[ $temp != "" ]] && echo ${temps[@]} | tr " " "\n" | jq -cs '.' || echo 255
# }

get_temp_json () {
  # check_cli_output

  # local temps=
  # for i in {0..4}; do
  #   temps+=`cat $CLI_OUTPUT | grep "Temperature No. $i" | cut -d " " -f 5`" "
  # done
  local t_value
  if [[ -f $CLI_OUTPUT ]]; then
    #if there is BME280 #0 Climate sensor, than take its temperature:
    t_value=`cat $CLI_OUTPUT | grep "BME280 No. 0 Temp: " | cut -d " " -f 5`
    if [[ ! -z $t_value && $t_value != '-nan' ]]; then
      temps+="$t_value "
    else
      temps+=`cat $CLI_OUTPUT | grep "Temperature No. 0" | cut -d " " -f 5`" " #in
    fi
    t_value=`cat $CLI_OUTPUT | grep "BME280 No. 1 Temp: " | cut -d " " -f 5`
    if [[ ! -z $t_value && $t_value != '-nan' ]]; then
      temps+="$t_value "
    else
      temps+=`cat $CLI_OUTPUT | grep "Temperature No. 1" | cut -d " " -f 5`" " #out
    fi
    local psu_count=`cat $CLI_OUTPUT | grep "PSU No." | tail -1 | cut -d " " -f 4`
    if [[ ! -z $psu_count ]]; then
      temps+=`cat $CLI_OUTPUT | grep "PSU" | grep "T1:" | cut -d " " -f 6 | awk '{sum+=$1} END { printf "%.2f", sum/NR }'`" " #mean intake temp
      temps+=`cat $CLI_OUTPUT | grep "PSU" | grep "T2:" | cut -d " " -f 6 | awk '{sum+=$1} END { printf "%.2f", sum/NR }'` #mean exhast temp
      # temps+=`cat $CLI_OUTPUT | grep "PSU T1:" | cut -d " " -f 4`" " #psu intake temp
      # temps+=`cat $CLI_OUTPUT | grep "PSU T2:" | cut -d " " -f 4`" " #psu exhast temp
      #temps+=`cat $CLI_OUTPUT | grep "PSU T3:" | cut -d " " -f 4`" " #psu board temp
    fi

    echo ${temps[@]} | tr " " "\n" | jq -cs '.'
  else
    echo "[]"
  fi
}

get_psu_json () {
  # check_cli_output
  if [[ -f $CLI_OUTPUT ]]; then
    voltage_ac=0; power_ac=0; voltage_dc=0
    result_json='{"units": []}'
    #get number of PSUs
    local psu_count=`cat $CLI_OUTPUT | grep "PSU No." | tail -1 | cut -d " " -f 4`
    if [[ -z $psu_count ]]; then
      echo "{}"
      return 1
    fi

    for (( i = 0; i <= $psu_count; i++ )); do
      local t_model=`cat $CLI_OUTPUT | grep "PSU No. $i" | tail -1 | cut -d " " -f 1`
      [[ -z $t_model ]] && continue
      local t_voltage_ac=`cat $CLI_OUTPUT | grep "PSU No. $i Vac:" | cut -d " " -f 6`
      [[ -z $t_voltage_ac ]] && t_voltage_ac=0
      local t_power_ac=`cat $CLI_OUTPUT | grep "PSU No. $i Pac:" | cut -d " " -f 6`
      [[ -z $t_power_ac ]] && t_power_ac=0
      local t_voltage_dc=`cat $CLI_OUTPUT | grep "PSU No. $i Vdc:" | cut -d " " -f 6`
      [[ -z $t_voltage_dc ]] && t_voltage_dc=0
      # local t_temp_in=`cat $CLI_OUTPUT | grep "PSU No. $i T1:" | cut -d " " -f 6`
      # [[ -z $t_temp_in ]] && t_temp_in=0
      # local t_temp_out=`cat $CLI_OUTPUT | grep "PSU No. $i T2:" | cut -d " " -f 6`
      # [[ -z $t_temp_out ]] && t_temp_out=0
      # local amperage_ac=`cat $CLI_OUTPUT | grep "PSU Iac:" | cut -d " " -f 4`
      # local amperage_dc=`cat $CLI_OUTPUT | grep "PSU Idc:" | cut -d " " -f 4`
      # local power_dc=`cat $CLI_OUTPUT | grep "PSU Pdc:" | cut -d " " -f 4`

      # Normalize PSU power
      if (( `echo "$t_power_ac < 30" | bc -l` && `echo "$t_power_ac != 0" | bc -l` )); then
        if [[ -f ${PSU_LAST_POWER_FILENAME}_$i ]]; then
          a=0
          let a=`date +%s`-`stat --format='%Y' ${PSU_LAST_POWER_FILENAME}_$i`
          [[ a -le 60 ]] &&  t_power_ac=`cat ${PSU_LAST_POWER_FILENAME}_$i | tail -1` || t_power_ac=0
        else
          t_power_ac=0
        fi
      else
        echo $t_power_ac > ${PSU_LAST_POWER_FILENAME}_$i
      fi
      [[ -z $t_power_ac ]] && t_power_ac=0

      voltage_ac=`echo "scale=1;$voltage_ac + $t_voltage_ac" | bc`
      power_ac=`echo "scale=1;$power_ac + $t_power_ac" | bc`
      voltage_dc=`echo "scale=1;$voltage_dc + $t_voltage_dc" | bc`
      result_json=`jq '.units += [{"id": '$i',
                                   "model": "'$t_model'",
                                   "power_ac": '$t_power_ac',
                                   "voltage_ac": '$t_voltage_ac',
                                   "voltage_dc": '$t_voltage_dc'}]' <<< $result_json`

                                   # "temp_in": '$t_temp_in',
                                   # "temp_out": '$t_temp_out'
    done

    # calc mean values
    if [[ $psu_count -gt 0 ]]; then
      voltage_ac=`echo "scale=1;$voltage_ac / ($psu_count + 1)" | bc`
      voltage_dc=`echo "scale=1;$voltage_dc / ($psu_count + 1)" | bc`
    fi

    # jq -cns \
    #    --arg voltage_ac $voltage_ac \
    #    --arg amperage_ac $amperage_ac \
    #    --arg power_ac $power_ac \
    #    --arg voltage_dc $voltage_dc \
    #    --arg amperage_dc $amperage_dc \
    #    --arg power_dc $power_dc \
    #    '{$voltage_ac, $amperage_ac, $power_ac, $voltage_dc, $amperage_dc, $power_dc}'

    t_json='{"power_ac": '$power_ac', "voltage_ac": '$voltage_ac', "voltage_dc": '$voltage_dc'}'
    jq -s '.[0] * .[1]' <<< "$result_json $t_json"
  else
    echo "{}"
  fi
}

get_fan_json_percent () {
  # check_cli_output
  if [[ -f $CLI_OUTPUT ]]; then
    local fans=
    local fan=0
    for j in {0..11}; do
      local fan_max_rpm=`cat $CLI_OUTPUT | grep "FAN No. $j max RPM:" | cut -f 6 -d " "`
      [[ -z $fan_max_rpm || $fan_max_rpm == '-nan' || $fan_max_rpm -eq 0 ]] && continue

      fan=`cat $CLI_OUTPUT | grep "FAN No. $j RPM in percent:" | cut -d " " -f 7`
      fans+=$fan" "
    done

    echo ${fans[@]} | tr " " "\n" | jq -cs '.'
  else
    echo "[]"
  fi
}

get_bme_json () {
  #[{"id": 0, "model": "BME280", "humid": 26.54, "press": 1014.12}, {"id": 1, "model": "BME280", "humid": 28.72, "press": 1013.49}]
  if [[ -f $CLI_OUTPUT ]]; then
    local bme_result
    local bme_count=`cat $CLI_OUTPUT | grep "BME" | tail -1 | cut -d " " -f 3`
    if [[ ! -z $bme_count ]]; then
      for (( i = 0; i <= $bme_count; i++ )); do
        local model=`cat $CLI_OUTPUT | grep "BME" | grep " No. $i Humid: " | cut -d " " -f 1`
        local humid=`cat $CLI_OUTPUT | grep "BME" | grep " No. $i Humid: " | cut -d " " -f 5`
        local press=`cat $CLI_OUTPUT | grep "BME" | grep " No. $i Press: " | cut -d " " -f 5`
        bme_result+=${bme_result:+,}'{"id": '$i', "model": "'$model'", "humid": '$humid', "press": '$press'}'
      done
    fi
    echo "[$bme_result]" | jq -c '.'
  else
    echo "[]"
  fi
}

check_avrdude () {
  if [[ `dpkg -s avrdude 2>/dev/null | grep -c "ok installed"` -eq 0 ]]; then
    [[ -f "/etc/avrdude.conf" ]] && rm -f "/etc/avrdude.conf"
    apt-get install -y avrdude
#    cp /hive/opt/octofan/avrdude.conf   /etc/avrdude.conf
  fi
}

check_snmpd () {
  if [[ `dpkg -s snmpd 2>/dev/null | grep -c "ok installed"` -eq 0 ]]; then
    [[ -f "/etc/snmp/snmpd.conf" ]] && rm -f "/etc/snmp/snmpd.conf"
    apt-get install -y snmpd
    if [[ ! -L /etc/snmp/snmpd.conf ]]; then #check for symlink
      mv /etc/snmp/snmpd.conf /etc/snmp/snmpd~.conf
      ln -sf /hive/etc/snmpd.conf /etc/snmp/snmpd.conf
    fi
    service snmpd restart
  fi
}

update_fw () {
  #check settings
  [[ -z $FW_FILENAME ]] && echo "FW_FILENAME is empty" && return 1
  [[ -z $FIRMWARE_MD5 ]] && echo "FIRMWARE_MD5 is empty" && return 1
  [[ -z $FW_VERSION ]] && echo "FW_VERSION is empty" && return 1

  echo "$(date +"%Y-%m-%d %T") - update firmware" > $MAINTENANCE_SEM_NAME

  echo2 "${GREEN}$(date +"%Y-%m-%d %T")${NOCOLOR}"
  echo2 "Updating fan controller firmware | FW_FILENAME=$FW_FILENAME | FW_VERSION=$FW_VERSION | FIRMWARE_MD5=$FIRMWARE_MD5 |"
  echo2 "Checking firmware MD5 sum"

  local fw_sum="null"
  fw_sum=`md5sum $FW_FILENAME | cut -f 1 -d " "`
  if [[ ! $FIRMWARE_MD5 == $fw_sum ]]; then
    echo2 "Firmware MD5 sum mismatch. ${RED}Firmware update aborted.${NOCOLOR}"
    rm -f ${MAINTENANCE_SEM_NAME}
    return 1
  else

    local error_txt=
    local t_error_txt=
    local bl_enter=0
    local error=0

    local bin_dir=`dirname "$OCTOFAN_BIN"`
    cd $bin_dir

    echo2 "${GREEN}$(date +"%Y-%m-%d %T")${NOCOLOR}"
    echo2 "Stopping miner"
    miner stop
    sleep 10

    echo2 "${GREEN}$(date +"%Y-%m-%d %T")${NOCOLOR}"
    echo2 "Entering bootloader"
    t_error_txt=`$OCTOFAN_BIN -b 2>&1`
    if [[ $? -ne 0 ]]; then
      error=1
      error_txt+="$(date +"%Y-%m-%d %T") Error on entering bootloader: $t_error_txt "
    else
      bl_enter=1
    fi
    sleep 1

    if [[ $bl_enter == 1 ]]; then
      cp /hive/opt/octofan/avrdude.conf /etc/avrdude.conf
      echo2 "${GREEN}$(date +"%Y-%m-%d %T")${NOCOLOR}"
      echo2 "Flashing the firmware $FW_FILENAME"

      #echo2 "/usr/bin/avrdude -pm328pb -cusbasp -Uflash:w:$FW_FILENAME:a"
      #t_error_txt=`/usr/bin/avrdude -pm328pb -cusbasp -Uflash:w:$FW_FILENAME:a 2>&1`
      #echo2 "/usr/bin/avrdude -pm324pb -cusbasp -U lfuse:w:0xff:m -U hfuse:w:0xd8:m -U efuse:w:0xfd:m -U flash:w:$FW_FILENAME:a"
      #t_error_txt=`/usr/bin/avrdude -pm324pb -cusbasp -U lfuse:w:0xff:m -U hfuse:w:0xd8:m -U efuse:w:0xfd:m -U flash:w:$FW_FILENAME:a 2>&1`
      echo2 "/usr/bin/avrdude -pm324pb -cusbasp -U flash:w:$FW_FILENAME:a"
      t_error_txt=`/usr/bin/avrdude -pm324pb -cusbasp -U flash:w:$FW_FILENAME:a 2>&1`
      if [[ $? -ne 0 ]]; then
        #one more try
        t_error_txt=`/usr/bin/avrdude -pm324pb -cusbasp -U flash:w:$FW_FILENAME:a 2>&1`
        if [[ $? -ne 0 ]]; then
          error=1
          error_txt+="$(date +"%Y-%m-%d %T") Error on flashing firmware: $t_error_txt "
        fi
      fi
      sleep 3
    fi

     echo2 "${GREEN}$(date +"%Y-%m-%d %T")${NOCOLOR}"
     echo2 "Exiting bootloader"
     t_error_txt=`$OCTOFAN_BIN -bx 2>&1`
     if [[ $? -ne 0 ]]; then
       error=1
       error_txt+="$(date +"%Y-%m-%d %T") Error on exiting bootloader: $t_error_txt "
     fi
     sleep 3

    #checking firmvare
    echo2 "Checking firmware"
    local fw_cur_ver=`$OCTOFAN_BIN -r | grep "VERSION-FW:" | cut -f 2 -d " "`
    dpkg --compare-versions "$FW_VERSION" "le" "$fw_cur_ver"
    if [ $? -ne "0" ]; then
      error=1
      error_txt+="$(date +"%Y-%m-%d %T") Firmware not updated, current version: $fw_cur_ver "
    fi
    sleep 3


    echo2 "${GREEN}$(date +"%Y-%m-%d %T")${NOCOLOR}"
    echo2 "Starting miner"
    miner start
    sleep 3

    #maintenance sem remooving in recalibrate_fans function
    recalibrate_fans

    if [[ $error == 0 ]]; then

      save_text_to_EEPROM

      echo2 ""
      echo2 "${GREEN}$(date +"%Y-%m-%d %T")${NOCOLOR}"
      echo2 "Done"
    else
      error_txt="Error on updating fan controller firmware: $error_txt"
      /hive/bin/message danger "$error_txt"
    fi
  fi
}

test_max_rpm () {
  echo2 "${GREEN}$(date +"%Y-%m-%d %T")${NOCOLOR}"
  echo2 "Testing max fans RPM"

  $OCTOFAN_BIN -t
  # for (( i=1; i<=70; i++)); do
  #   echo -n '.'
  #   sleep 0.5
  # done
}

get_max_rpm_json () {
  check_cli_output

  local fan=
  local fans=

  for f in {0..11}; do
    fan=`cat $CLI_OUTPUT | grep "FAN No. $f max RPM:" | cut -f 6 -d " "`
    [[ -z $fan || $fan == '-nan' ]] && fan=0

    fans+=${fans:+,}'"fan'${f}'_max_rpm": '$fan
  done

  echo "{$fans}" | jq -c .
}

recalibrate_fans () { #native recalibration (-t) takes too much time this function is near five times faster
  #create maintenance sem
  echo "$(date +"%Y-%m-%d %T") - recalibrate fans" > $MAINTENANCE_SEM_NAME

  #remove manual max rpm from config
  sed -i 's/.*MAX_RPM.*//' $OCTOFAN_CONF

  load_def_values

  echo2 "${GREEN}$(date +"%Y-%m-%d %T")${NOCOLOR}"
  echo2 "Setting fans speed to max"
  for i in {0..11}; do
    $OCTOFAN_BIN -f $i -v 255
    sleep 0.1
  done

  #time to spin up fans
  sleep 4.4

  echo2 "${GREEN}$(date +"%Y-%m-%d %T")${NOCOLOR}"
  echo2 "Testing max fans RPM"

  local fans_max_rpm=()
  local t_rpm=0
  for t in {1..5}; do
    $OCTOFAN_BIN -r > $CLI_OUTPUT
    for i in {0..11}; do
      t_rpm=`cat $CLI_OUTPUT | grep "FAN No. $i RPM:" | cut -d " " -f 5`
      [[ ${fans_max_rpm[$i]} -lt $t_rpm ]] && fans_max_rpm[$i]=$t_rpm
      #sleep 0.1
    done
    sleep 0.7
  done

  echo2 "${GREEN}$(date +"%Y-%m-%d %T")${NOCOLOR}"
  echo "Saving max values: ${fans_max_rpm[@]}"
  for i in {0..11}; do
    [[ ! -z ${fans_max_rpm[$i]} ]] && t_rpm=${fans_max_rpm[$i]} || t_rpm=0
    $OCTOFAN_BIN -m $i -v $t_rpm
    if [[ $t_rpm -gt 0 ]]; then
      if [[ $t_rpm -le $ERROR_RPM ]]; then
        message error "Casefan #$i have max RPM $t_rpm."
      elif [[ $t_rpm -le $WARNING_RPM ]]; then
        message warning "Casefan #$i have max RPM $t_rpm."
      fi
    fi
    sleep 0.1
  done

  #refresh cli output
  $OCTOFAN_BIN -r > $CLI_OUTPUT

  #remove maintenance sem
  rm -f ${MAINTENANCE_SEM_NAME}

  return 0
}

check_firmware () {
  local fw_cur_ver=`$OCTOFAN_BIN -r | grep "VERSION-FW:" | cut -f 2 -d " "`
  echo2 "Current FW version is: $fw_cur_ver"
  local hw_cur_ver=`$OCTOFAN_BIN -r | grep "VERSION-HW:" | cut -f 2 -d " "`
  echo2 "Current HW version is: $hw_cur_ver"

  case $hw_cur_ver in
    "0.9" )
        FW_VERSION=$FW_VERSION_09
        dpkg --compare-versions "$FW_VERSION" "le" "$fw_cur_ver"
        if [ $? -ne "0" ]; then
          check_avrdude
          FW_FILENAME=$FW_FILENAME_09
          FIRMWARE_MD5=$FIRMWARE_MD5_09
          update_fw
        fi
      ;;
    "0.7" )
        FW_VERSION=$FW_VERSION_07
        dpkg --compare-versions "$FW_VERSION" "le" "$fw_cur_ver"
        if [ $? -ne "0" ]; then
          check_avrdude
          FW_FILENAME=$FW_FILENAME_07
          FIRMWARE_MD5=$FIRMWARE_MD5_07
          update_fw
        fi
      ;;
    * )
        echo2 "No firmware updates for your hardware"
      ;;
  esac
}

check_sem () {
if [[ -f $MAINTENANCE_SEM_NAME ]]; then
  a=0
  let a=`date +%s`-`stat --format='%Y' $MAINTENANCE_SEM_NAME`
  if [[ a -le 60 ]]; then
    echo2 "Octofan is in maintenance mode. Command ignored."
    return 1 #octofan in maintenance mode
  else
    return 0
  fi
fi
}

function log_truncate () {
  [[ ! -e $CLI_LOG_BASE_NAME.log ]] && return 0

  local fsize=`stat -c%s $CLI_LOG_BASE_NAME.log`
  [[ ! -z $fsize && $fsize -ge $MAX_LOG_SIZE ]] &&
    echo "*** truncated by $0" > $CLI_LOG_BASE_NAME.log

  return 0
}

function logs_rotate () {
  # Make sure logs dir exists
  mkdir -p $CLI_LOGS_BASE_DIR

  [[ -e $CLI_LOG_BASE_NAME.log.5 ]] && rm $CLI_LOG_BASE_NAME.log.5
  [[ -e $CLI_LOG_BASE_NAME.log.4 ]] && mv -f $CLI_LOG_BASE_NAME.log.4 $CLI_LOG_BASE_NAME.log.5
  [[ -e $CLI_LOG_BASE_NAME.log.3 ]] && mv -f $CLI_LOG_BASE_NAME.log.3 $CLI_LOG_BASE_NAME.log.4
  [[ -e $CLI_LOG_BASE_NAME.log.2 ]] && mv -f $CLI_LOG_BASE_NAME.log.2 $CLI_LOG_BASE_NAME.log.3
  [[ -e $CLI_LOG_BASE_NAME.log.1 ]] && mv -f $CLI_LOG_BASE_NAME.log.1 $CLI_LOG_BASE_NAME.log.2
  [[ -e $CLI_LOG_BASE_NAME.log ]] && mv -f $CLI_LOG_BASE_NAME.log $CLI_LOG_BASE_NAME.log.1

  return 0
}

function echo_log () {
  echo2 "$1" >> $CLI_LOG_BASE_NAME.log
}

function write_cli_log () {
  check_cli_output
  echo_log "$(date +"%Y-%m-%d %T")"

  local t_fans
  for (( i = 0; i < ${#FAN_ARRAY[@]}; i++ )); do
    t_fans+="Case FAN$i "`cat $CLI_OUTPUT | grep "FAN No. $i RPM:" | cut -d " " -f 5`"rpm   "
  done

  local in_t=`cat $CLI_OUTPUT | grep "BME280 No. 0 Temp: " | cut -d " " -f 5`
  [[ -z $in_t || $in_t == '-nan' ]] && in_t=`cat $CLI_OUTPUT | grep "Temperature No. 0" | cut -d " " -f 5`
  local out_t=`cat $CLI_OUTPUT | grep "BME280 No. 1 Temp: " | cut -d " " -f 5`
  [[ -z $out_t || $out_t == '-nan' ]] && out_t=`cat $CLI_OUTPUT | grep "Temperature No. 1" | cut -d " " -f 5`
  echo_log "Case temperature intake: ${in_t}°C   outgoing: ${out_t}°C"

  local psu_count=`cat $CLI_OUTPUT | grep "PSU No." | tail -1 | cut -d " " -f 4`
  if [[ ! -z $psu_count ]]; then
    for (( i = 0; i <= $psu_count; i++ )); do
      local t_model=`cat $CLI_OUTPUT | grep "PSU No. $i" | tail -1 | cut -d " " -f 1`
      local t_voltage_ac=`cat $CLI_OUTPUT | grep "PSU No. $i Vac:" | cut -d " " -f 6`
      local t_power_ac=`cat $CLI_OUTPUT | grep "PSU No. $i Pac:" | cut -d " " -f 6`
      local t_voltage_dc=`cat $CLI_OUTPUT | grep "PSU No. $i Vdc:" | cut -d " " -f 6`
      echo_log "PSU$i $t_model Vac: ${t_voltage_ac}V   Pac: ${t_power_ac}W   Vdc: ${t_voltage_dc}V"

      local psu_in_t=`cat $CLI_OUTPUT | grep "PSU" | grep "T1:" | cut -d " " -f 6 | awk '{sum+=$1} END { printf "%.0f", sum/NR }'` #mean intake temp
      local psu_out_t=`cat $CLI_OUTPUT | grep "PSU" | grep "T2:" | cut -d " " -f 6 | awk '{sum+=$1} END { printf "%.0f", sum/NR }'` #mean exhast temp
      echo_log "     temperature intake: ${psu_in_t}°C   outgoing: ${psu_out_t}°C" #   board: ${psu_board_t}°C
    done
  fi

  echo_log ""
}

if [ ! $1 = "" ]; then
  check_sem
  [[ $? -ne 0 ]] && exit 1 #octofan in maintenance mode
fi

# load_def_values

if [[ $1 == "get_fan_json" || $1 == "-f" ]]; then
  get_fan_json_percent
elif [[ $1 == "get_temp_json" || $1 == "-t" ]]; then
  get_temp_json
elif [[ $1 == "get_psu_json" || $1 == "-p" ]]; then
  get_psu_json
elif [[ $1 == "get_bme_json" || $1 == "-b" ]]; then
  get_bme_json
elif [[ `lsusb | grep -c 16c0:05dc` -ge 1 ]]; then
  if [[ $1 == "update_text" || $1 == "-ut" ]];  then
    update_text $2 $3
  elif [[ $1 == "write_cli_log" || $1 == "-wl" ]]; then
    write_cli_log
  elif [[ $1 == "blink_error" || $1 == "-e" ]]; then
    blink_error
  elif [[ $1 == "blink_warning"|| $1 == "-w" ]]; then
    blink_warning
  elif [[ $1 == "blink_off" || $1 == "-off" ]]; then
    blink_off
  elif [[ $1 == "log_truncate" || $1 == "-tl" ]]; then
    log_truncate
  elif [[ $1 == "run" ]]; then
    # recalibrate_fans
    load_def_values
    check_config
    logs_rotate
    check_firmware | tee "$FIRMWARE_UPDATE_LOG"
    check_snmpd

    octo_fan_control
  elif [[ $1 == "save_text_to_EEPROM" ]]; then
    save_text_to_EEPROM
  # elif [[ $1 == "get_fan" ]]; then
  #   [[ ! -z $2 ]] && echo `calc_fan_speed $2`
  # elif [[ $1 == "get_temp" ]]; then
  #   get_temp $2
  elif [[ $1 == "recalibrate" || $1 == "-r" ]]; then
    recalibrate_fans
  elif [[ $1 == "dontattach" ]]; then
    session_count=`screen -ls octofan | grep octofan | wc -l`
    if [[ $session_count -eq 0 ]]; then
      #start new screen
      echo2 "> Starting octofan"
      screen -dm -S octofan $0 run
      echo2 "Octofan screen started"
    fi
  elif [[ $1 == "get_max_rpm_json" || $1 == "-m" ]]; then
    get_max_rpm_json
  elif [[ $1 == "logs_rotate" || $1 == "-rl" ]]; then
    logs_rotate
  elif [[ $1 == "" ]]; then
    session_count=`screen -ls octofan | grep octofan | wc -l`
    if [[ $session_count -gt 0 ]]; then
      screen -x -S octofan
    else #start new screen
      echo2 "> Starting octofan"
      screen -dm -S octofan $0 run
      echo2 "Octofan screen started"
    fi
  fi
else
  echo "No Octofan hardware found"
fi
exit 0
