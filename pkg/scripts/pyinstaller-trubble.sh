#!/bin/bash

_check_auto_deletion=$2
pushd ../../
_SOURCE_DIR="./"
_HOOK_DIR="./pkg/"
_BINARY_LOG_LEVEL="INFO"

function pkg_init {
_INCLUDE_PATH=""

pyinstaller --onedir \
  --noconfirm \
  --log-level $_BINARY_LOG_LEVEL \
  --additional-hooks-dir=$_HOOK_DIR \
  $_INCLUDE_PATH \
  trubble.py
}

function pkg_clean {
  declare -a check_folders=('build' 'dist' '/opt/trubble' '/opt/osquery')

  for i in "${check_folders[@]}"
  do
    if [[ -f $i ]];
    then

      if [[ "$_check_auto_deletion" == "-y" ]];
      then
        _input="y"
      else
        read -r -p "The file $i will be deleted, do you agree : [y/n]" _input
      fi

      if [[ "$_input" == "y" ]];
      then
        echo "removing $i ..."
        rm -rf $i
      else
        echo "skipping deletion of $i"
      fi

    elif [[ -d $i ]];
    then

      if [[ "$_check_auto_deletion" == "-y" ]];
      then
        _input="y"
      else
        read -r -p "The folder $i will be deleted, do you agree : [y/n]" _input
      fi

      if [[ "$_input" == "y" ]];
      then
        echo "removing $i/* ..."
        rm -rf $i/*
      else
        echo "skipping deletion of $i"
      fi

    else
      rm -f $i
    fi
  done

}

function pkg_create {
cp -rf conf/trubble /etc/trubble/
cp -rf conf/trubble-profile.sh /etc/profile.d/
cp -pr dist/trubble /opt/trubble/trubble-libs
ln -s /opt/trubble/trubble-libs/trubble /opt/trubble/trubble
cp -rf conf/trubble /etc/trubble/
tar -cPvzf trubble.tar.gz /etc/trubble /etc/osquery /opt/trubble /opt/osquery /var/log/osquery /etc/profile.d/trubble-profile.sh
}

$1
popd
