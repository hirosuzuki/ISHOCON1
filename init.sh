#!/bin/sh

cd ./admin

# create user
sudo mysql -e "CREATE USER 'ishocon'@'%' IDENTIFIED BY 'ishocon'"

# initialize webapp database
sudo mysql -e "CREATE DATABASE ishocon1 CHARACTER SET utf8mb4"
sudo mysql -e "GRANT ALL PRIVILEGES ON ishocon1.* TO 'ishocon'@'%'"
sudo mysql ishocon1 < init.sql
RAND_SEED=1 ruby insert.rb

# initialize admin database
sudo mysql -e "CREATE DATABASE ishocon1admin CHARACTER SET utf8mb4"
sudo mysql -e "GRANT ALL PRIVILEGES ON ishocon1admin.* TO 'ishocon'@'%'"
sudo mysql ishocon1admin < init.sql
RAND_SEED=1 ISHOCON1_DB_NAME=ishocon1admin ruby insert.rb

# build benchmark app
go get
go build -o benchmark
