# Installing required packages

if [ -f "/usr/bin/apt-get" ]
then
  apt-get update
  apt-get install python-dev libffi-dev libssl-dev libxml2-dev libxslt1-dev libjpeg8-dev zlib1g-dev make cmake python-setuptools gcc wget git -y
elif [ -f "/usr/bin/yum" ]
then
  yum install python27-devel libffi-devel openssl-devel libxml2-devel libxslt-devel libjpeg-devel zlib-devel make cmake python27-setuptools python27-python-setuptools gcc python-devel python-setuptools git wget -y
else
  echo "No package managers found ..."
  exit
fi

easy_install pip

# Creating required directories
mkdir -p /etc/osquery /var/log/osquery /etc/trubble /opt/trubble /opt/osquery /var/osquery
