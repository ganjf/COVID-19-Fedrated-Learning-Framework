# -*- coding: utf-8 -*-
import os
import pdb
import json
import torch
import logging
from time import sleep
from model.model import densenet3d
from common.LWE_based_PHE.cuda_test import KeyGen, Enc, Dec
from encrypt_decrypt import generate_shape, encrypt, decrypt
from socket import socket, AF_INET, SOCK_STREAM, SOL_SOCKET, SO_REUSEADDR
from common.tcp_utils import send_head_dir, recv_head_dir, recv_and_write_file, send_file


class FL_Client(object):
    def __init__(self, config_path, shape_param_path='./config/shape_parameter.pth'):
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

        with open(config_path, 'r') as j:
            self.configs = json.load(j)

        self.ip_port = (self.configs["ip"], self.configs["send_port"])
        self.server_ip_port = (self.configs['server_ip'], self.configs['server_port'])

        self.seed = self.configs['seed']
        self.model = densenet3d().cuda()
        self.pk, self.sk = KeyGen(self.seed)  # generate public_key and private_key

        if os.path.exists(shape_param_path):
            pass
        else:
            model_weight = self.model.state_dict()
            generate_shape(shape_param_path, model_weight)

        self.shape_parameter = torch.load(shape_param_path)

        self.weight = None
        self.model_path = self.configs["model_path"]
        self.train_model_path = self.configs["weight_path"]

    def start(self):
        self.logger.info("client begin")
        self.register()

    def stop(self):
        self.logger.info("training finished,  client quiting...")
        exit()

    def register(self):
        self.logger.info("register with server ...")
        send_socket = socket(AF_INET, SOCK_STREAM)
        try:
            send_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            send_socket.bind(self.ip_port)
            send_socket.connect(self.server_ip_port)

            head_dir = json.dumps({'username': self.configs['username'],
                                   'password': self.configs['password'],
                                   'msg': "register"})
            send_head_dir(conn=send_socket, head_dir=head_dir)
            recv_dir = recv_head_dir(conn=send_socket)

            if recv_dir["msg"] == "ok":
                # receive and save model.py from clients
                recv_and_write_file(conn=send_socket,
                                    file_dir='/'.join(self.model_path.split("/")[:-1]) + "/",
                                    buff_size=self.configs["buff_size"])
                self.logger.info("successfully registered!")
            else:
                self.stop()
        finally:
            send_socket.close()
            sleep(5)

    def request_model(self):
        self.logger.info("Request server sending model...")
        send_socket = socket(AF_INET, SOCK_STREAM)
        try:
            send_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            send_socket.bind(self.ip_port)
            send_socket.connect(self.server_ip_port)

            head_dir = json.dumps({'username': self.configs['username'], 'msg': "request_model"})
            send_head_dir(conn=send_socket, head_dir=head_dir)
            recv_dir = recv_head_dir(conn=send_socket)

            if recv_dir["msg"] == "finish":
                self.stop()

            if recv_dir["msg"] == "ok":
                fileName = recv_and_write_file(conn=send_socket,
                                               file_dir='/'.join(self.model_path.split("/")[:-1]) + "/",
                                               buff_size=self.configs['buff_size'])
                savedPath = os.path.join('/'.join(self.model_path.split("/")[:-1]) + "/", fileName)
                self.train_model_path = savedPath
                self.logger.info("Successfully received the server model!")
                return "ok"
            elif recv_dir["msg"] == "wait":
                self.logger.info("waiting...")
                return "wait"
            else:
                self.logger.warning("requested model was rejected!")
                return "error"
        finally:
            send_socket.close()
            sleep(1)

    def send_model(self, model_weight_path=None, versionNum=0):
        send_socket = socket(AF_INET, SOCK_STREAM)
        try:
            send_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            send_socket.bind(self.ip_port)
            send_socket.connect(self.server_ip_port)

            head_dir = json.dumps({'username': self.configs['username'], 'msg': "send_model"})
            send_head_dir(conn=send_socket, head_dir=head_dir)
            recv_dir = recv_head_dir(conn=send_socket)

            if recv_dir["msg"] == "finish":
                self.stop()

            if recv_dir["msg"] == "ok":
                self.logger.info("send model to server...")
                if model_weight_path is None:
                    send_path = self.configs["weight_path"]
                else:
                    send_path = model_weight_path
                send_file(conn=send_socket, file_path=send_path,
                          new_file_name="model_Param_{}_v_{}.pth".format(self.configs["username"], versionNum))
                self.logger.info("successfully sent the model to the server!")
                return "ok"
            else:
                self.logger.warning("the sending model was rejected!")
                return "error"
        finally:
            send_socket.close()
            sleep(1)

    def set_weight(self, weight=1.0):
        self.weight = weight

    def pack_param(self, _model_state, _client_weight, save_path=None):
        ob = {"model_state_dict": _model_state,
              "client_weight": _client_weight}

        if save_path is not None:
            torch.save(ob, save_path)
        else:
            torch.save(ob, self.configs["weight_path"])

    @staticmethod
    def unpack_param(_model_param_path):
        ob = torch.load(_model_param_path)
        state = ob['model_state_dict']
        client_weight = ob['client_weight']
        client_num = ob['client_num']

        return state, client_weight, client_num

    def enc_num(self, num):
        return Enc(self.pk, num)

    def dec_num(self, num):
        return Dec(self.sk, num)

    def encrypt(self, model_weight):
        encrypt_params = encrypt(self.pk, model_weight)
        return encrypt_params

    def decrypt(self, encrypted_model_weight, client_num):
        decrypt_params = decrypt(self.sk, encrypted_model_weight, client_num, self.shape_parameter)
        return decrypt_params
