#!/bin/bash 
#这里可替换为你自己的执行程序,其他代码无需更改 
APP_NAME=main.py
BASE_DIR=$(cd $(dirname $0);pwd)
PARENT_DIR=$(dirname $BASE_DIR)
PY_HOME=python
cd $BASE_DIR
install(){
	python -m pip install -r requirements.txt
}
#使用说明,用来提示输入参数 
usage() { 
	echo "Usage: sh 执行脚本.sh [start|stop|restart|status|startTest]" 
	exit 1 
} 
#检查程序是否在运行 
is_exist(){ 
	pid=`ps -ef|grep $BASE_DIR/$APP_NAME|grep -v grep|awk '{print $2}' ` 
	#如果不存在返回1,存在返回0 
	if [ -z "${pid}" ]; then 
		return 1 
	else 
		return 0 
	fi 
} 
#启动方法 
start(){ 
	is_exist 
	if [ $? -eq "0" ]; then 
		echo "${APP_NAME} is already running. pid=${pid} ." 
	else 
		${PY_HOME} $BASE_DIR/$APP_NAME &
	fi
}
#停止方法 
stop(){ 
	for i in `seq 1 5`;
	  do
		is_exist 
		[ $? -eq "1" ] && break
		  kill $pid
		  echo -n "."
		  sleep 1
	  done
	echo ""  
	is_exist 
	if [ $? -eq "0" ]; then 
		kill -9 $pid 
		echo "${APP_NAME} force stopped successfully!" 
	else 
		echo "${APP_NAME} stopped successfully." 
	fi 
} 
#输出运行状态 
status(){ 
	is_exist 
	if [ $? -eq "0" ]; then 
		echo "${APP_NAME} is running. Pid is ${pid}" 
	else 
		echo "${APP_NAME} is NOT running." 
	fi 
} 
#重启 
restart(){ 
	stop 
	start 
} 
#检查项目是否启动成功
check(){
  is_exist
  if [ ! $? -eq "0" ]; then
    status
    return 1
  fi

  if [ "x${CHECK_URL}" = "x" ]; then
    echo "没有设置 CHECK_URL"
    return 2
  else
    echo "CHECK_URL=${CHECK_URL}"
    code=$(curl -I -s -m 2 ${CHECK_URL} | grep HTTP|awk '{print $2}')
    if [ ! x"$code" = "x" ] && [ ! "${code}" = "404" ]; then
      echo "[${APP_NAME}] 运行成功."
      return 0
    else
      echo "[${APP_NAME}] 启动中."
      return 1
    fi
  fi
}

#根据输入参数,选择执行对应方法,不输入则执行使用说明 
case "$1" in 
  "start")
    start
  ;;
  "stop")
    stop
  ;;
  "status")
    status
  ;;
  "restart")
    restart
  ;;
  "install")
    install
  ;;
  "check")
    check
  ;;
*) 
usage 
;; 
esac
