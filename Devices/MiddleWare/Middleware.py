import io
import json
import subprocess
import sys
import threading
import time
import functools
import argparse
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, accuracy_score
import pandas as pd

from Analytics.Analytics import Analytics
from MessageBroker.Consumer import Consumer
from MiddleWare.BlockChainClient import BlockChainConnection
from MiddleWare.NeuralNet import Network, FCLayer, mse_prime, mse
import os, sys
sys.path.append("/Users/chaehyeon/Documents/DPNM/2023/TUB/Advancing-Blockchain-Based-Federated-Learning-Through-Verifiable-Off-Chain-Computations")
from Devices.utils.utils import read_yaml

import hashlib, random
#+++++fix
from Devices.Edge_Device.Data import Data
from Devices.Edge_Device.Data import write_args_for_zokrates_cli



def print_report(device,model,X_test,y_test):
    print(f"{device}",classification_report(y_test,model.predict(X_test),zero_division=0))

class FederatedLearningModel:

    def __init__(self,config_file,deviceName):
        self.deviceName=deviceName
        self.config =config_file
        self.consumer = Consumer()
        self.scaler = StandardScaler()
        self.net = Network(self.config["DEFAULT"]["OutputDimension"],self.config["DEFAULT"]["InputDimension"],self.config["DEFAULT"]["Precision"] )
        self.net.add(FCLayer(self.config["DEFAULT"]["InputDimension"], self.config["DEFAULT"]["OutputDimension"]))
        self.epochs=self.config["DEFAULT"]["Epochs"]
        self.net.use(mse, mse_prime)
        self.learning_rate=None
        self.batchSize=None
        self.x_train=None
        self.y_train=None
        datasource = self.config["DEFAULT"]["TestFilePath"]
        testdata = pd.read_csv(
            datasource, names=
            ["T_xacc", "T_yacc", "T_zacc", "T_xgyro", "T_ygyro", "T_zgyro", "T_xmag", "T_ymag", "T_zmag",
             "RA_xacc", "RA_yacc", "RA_zacc", "RA_xgyro", "RA_ygyro", "RA_zgyro", "RA_xmag", "RA_ymag", "RA_zmag",
             "LA_xacc", "LA_yacc", "LA_zacc", "LA_xgyro", "LA_ygyro", "LA_zgyro", "LA_xmag", "LA_ymag", "LA_zmag",
             "RL_xacc", "RL_yacc", "RL_zacc", "RL_xgyro", "RL_ygyro", "RL_zgyro", "RL_xmag", "RL_ymag", "RL_zmag",
             "LL_xacc", "LL_yacc", "LL_zacc", "LL_xgyro", "LL_ygyro", "LL_zgyro", "LL_xmag", "LL_ymag", "LL_zmag",
             "Activity"]

        )
        testdata.fillna(inplace=True, method='backfill')
        testdata.dropna(inplace=True)
        testdata.drop(columns= ["T_xacc", "T_yacc", "T_zacc", "T_xgyro","T_ygyro","T_zgyro","T_xmag", "T_ymag", "T_zmag","RA_xacc", "RA_yacc", "RA_zacc", "RA_xgyro","RA_ygyro","RA_zgyro","RA_xmag", "RA_ymag", "RA_zmag","RL_xacc", "RL_yacc", "RL_zacc", "RL_xgyro","RL_ygyro","RL_zgyro" ,"RL_xmag", "RL_ymag", "RL_zmag","LL_xacc", "LL_yacc", "LL_zacc", "LL_xgyro","LL_ygyro","LL_zgyro" ,"LL_xmag", "LL_ymag", "LL_zmag"],inplace=True)
        activity_mapping = self.config["DEFAULT"]["ActivityMappings"]
        filtered_activities = self.config["DEFAULT"]["Activities"]
        activity_encoding = self.config["DEFAULT"]["ActivityEncoding"]
        for key in activity_mapping.keys():
            testdata.loc[testdata['Activity'] == key,'Activity'] = activity_mapping[key]
        testdata = testdata[testdata['Activity'].isin(filtered_activities)]
        for key in activity_encoding.keys():
            testdata.loc[testdata['Activity'] == key, 'Activity'] = activity_encoding[key]
        self.x_test = testdata.drop(columns="Activity")
        self.y_test = testdata["Activity"]

    def test_model(self):
        x_test=self.scaler.transform(self.x_test.to_numpy())
        pred=self.net.predict(x_test)
        return accuracy_score(self.y_test,self.net.predict(x_test))

    def get_classification_report(self):
        x_test=self.scaler.transform(self.x_test.to_numpy())
        return classification_report(self.y_test,self.net.predict(x_test),zero_division=0,output_dict=True)

    def process_Batch(self, x_train, y_train):
        self.x_train = x_train
        self.y_train = y_train
        self.scaler.fit(self.x_test.to_numpy())
        self.x_train = self.scaler.transform(self.x_train)
        self.net.fit(self.x_train, self.y_train, epochs=self.epochs, learning_rate=self.learning_rate)
        score = self.test_model()
        print(f"{self.deviceName}:Score :",score)

    def reset_batch(self):
        self.x_train=None
        self.y_train=None

    def get_weights(self):
        return self.net.get_weights()

    def get_bias(self):
        return self.net.get_bias()

    def set_learning_rate(self,rate):
        self.learning_rate=rate

    def set_weights(self,weights):
        self.net.set_weights(weights)

    def set_bias(self,bias):
        self.net.set_bias(bias)

    def set_batchSize(self,batchSize):
        self.batchSize=batchSize

    def set_precision(self,precision):
        self.net.set_precision(precision)

    # def add_data_to_current_batch(self,data):
    #     if self.curr_batch is None:
    #         self.curr_batch = data
    #     else:
    #         self.curr_batch=pd.concat([self.curr_batch,data])



class MiddleWare:

    def __init__(self,blockchain_connection,deviceName,accountNR,configFile):
        self.accountNR=accountNR
        self.consumer_thread=None
        self.analytics=Analytics(deviceName=deviceName,config_file=configFile)
        self.blockChainConnection=blockchain_connection
        self.deviceName=deviceName
        self.model=FederatedLearningModel(config_file=configFile,deviceName=self.deviceName)
        self.data = Data(blockchain_connection=blockchain_connection, deviceName=self.deviceName, accountNR=accountNR, configFile=configFile)
        self.config = configFile
        self.consumer = Consumer()
        self.__init_Consumer(deviceName,callback)
        self.proof=None
        self.precision=None
        self.batchSize=None
        self.round=0

    #+++++fix
    def _register_data_source_for_data_authenticity(self):
        print(f"{self.accountNR}, {self.deviceName}, regstration start")
        self.data.get_vc()
        self.data.proving()
        self.data.verification()
        print(f"{self.accountNR}, {self.deviceName}, regstration start")
        
 
    def __generate_Proof(self, w, b, w_new, b_new, x_train, y_train, learning_rate):
        print(f"{self.accountNR}, {self.deviceName}, proof generation start")
        
        x_train = x_train * self.precision
        b_new = b_new.reshape(self.config["DEFAULT"]["OutputDimension"],)
        x_train = x_train.astype(int)
        
        #Get commitment from Blockchain
        commitment = self.data.get_Commitment()
        #print(f"{self.deviceName}'s commitment: {commitment}")

        
        def args_parser(args):
            res = ""
            for arg in range(len(args)):
                entry = args[arg]
                if isinstance(entry, (list, np.ndarray)):
                    for i in range(len(entry)):
                        row_i = entry[i]
                        if isinstance(row_i, (list, np.ndarray)):
                            for j in range(len(row_i)):
                                val = row_i[j]
                                res += str(val) + " "
                        else:
                            res += str(row_i) + " "
                else:
                    res += str(args[arg]) + " "
            res = res[:-1]
            return res


        zokrates = "zokrates"
        zok_path = self.config["TEST"]["ZokratesPath"]
        verification_path = self.config["TEST"]["VerificationBase"]
        zokrates_path = zok_path + 'root.zok'
        out_path=zok_path+"out"
        abi_path = zok_path+"abi.json"
        witness_path= verification_path + "witness_" + self.deviceName
        proof_path=verification_path+"proof_" + self.deviceName
        proving_key_path=zok_path+"proving.key"

        weights, weights_sign = self.data.convert_matrix(w)
        bias, bias_sign = self.data.convert_matrix(b)
        weights_new, _ = self.data.convert_matrix(w_new)
        bias_new, _ = self.data.convert_matrix(b_new)
        x, x_sign = self.data.convert_matrix(x_train)
        args = [weights, weights_sign, bias, bias_sign, x, x_sign, y_train, learning_rate, self.precision, weights_new, bias_new]
        witness_args = args_parser(args).split(" ")

        print(f"{self.accountNR}, {self.deviceName}, merkleTree generation start")
        
        nLeaf, merkleRoot, merkleTree = self.data.auth.get_merkletree_poseidon(x, x_sign, y_train)
        #print(f"{self.deviceName}'s merkleRoot: {merkleRoot}")
        padding = bytes(32)
        padded_512_msg = bytes.fromhex(merkleRoot) + padding
        signature = self.data.auth.get_signature(padded_512_msg)
        merkle_args = write_args_for_zokrates_cli(self.data.auth.pk, signature, padded_512_msg, commitment).split(" ")
        #merkle_args = write_args_for_zokrates_cli( x, x_sign, y_train, self.data.auth.pk, signature, padded_512_msg, commitment).split(" ")
        witness_args.extend(merkle_args)
        print(f"{self.accountNR}, {self.deviceName}, signature generation end")


        with open("./zokrates_input.txt", "w+") as file:
            file.write(" ".join(map(str, witness_args)))


        #Zokrates file compile
        # zokrates_compile = [zokrates, "compile", '-i', zokrates_path, '-o',out_path,'-s', abi_path]
        # g = subprocess.run(zokrates_compile, capture_output=True)

        print(f"{self.accountNR}, {self.deviceName}, witness generation start")
        # #Witness computation
        zokrates_compute_witness = [zokrates, "compute-witness", "-o", witness_path, '-i',out_path,'-s', abi_path, '-a']
        zokrates_compute_witness.extend(witness_args)
        g = subprocess.run(zokrates_compute_witness, capture_output=True)
        
        print(f"{self.accountNR}, {self.deviceName}, proof generation start")
        # #Proof generation
        zokrates_generate_proof = [zokrates, "generate-proof",'-w',witness_path,'-p',proving_key_path,'-i',out_path,'-j',proof_path]
        g = subprocess.run(zokrates_generate_proof, capture_output=True)

        print(f"{self.accountNR}, {self.deviceName}, proof generation end ")

        with open(proof_path,'r+') as f:
            self.proof=json.load(f)


    def __init_Consumer(self,DeviceName,callBackFunction):
        queueName = self.config["DEFAULT"]["QueueBase"] + DeviceName
        on_message_callback = functools.partial(callBackFunction, args=(self.data))
        self.consumer.declare_queue(queueName)
        self.consumer.consume_data(queueName,on_message_callback)

    def __start_Consuming(self):
        self.consumer_thread=threading.Thread(target=self.consumer.start_consuming)
        self.consumer_thread.start()

    def update(self,w,b,p,r,balance):
        tu = time.time()
        self.blockChainConnection.update(w, b, self.accountNR, p)
        self.analytics.add_round_update_blockchain_time(r, time.time() - tu)
        self.analytics.add_round_gas(self.round, balance - self.blockChainConnection.get_account_balance(self.accountNR))

    def start_Middleware(self):
        self.__start_Consuming()
        self.blockChainConnection.init_contract(self.accountNR)
        self.round=self.blockChainConnection.get_RoundNumber(self.accountNR)
        print("Round ", self.round , f": {self.deviceName} in start_Middleware() ", sep=" ")
        self._register_data_source_for_data_authenticity()
        while self.config["DEFAULT"]["Rounds"]>self.round:
            print(f"{self.accountNR}, {self.deviceName}, round: ", self.round)
            outstanding_update=self.blockChainConnection.roundUpdateOutstanding(self.accountNR)
            # print(f"{self.accountNR}, {self.deviceName} outstanding_update in start_Middleware() MiddleWare.py")
            self.round = self.blockChainConnection.get_RoundNumber(self.accountNR)
            # print(self.round , f"{self.deviceName} in while clause in start_Middleware() 2 **** ", sep=" ")
            print(f"{self.accountNR}, {self.deviceName}: Round {self.round} Has update outstanding: ",outstanding_update)
            if(outstanding_update):
                t=time.time()
                balance=self.blockChainConnection.get_account_balance(self.accountNR)
                global_weights=self.blockChainConnection.get_globalWeights(self.accountNR)
                global_bias=self.blockChainConnection.get_globalBias(self.accountNR)
                lr=self.blockChainConnection.get_LearningRate(self.accountNR)
                self.precision=self.blockChainConnection.get_Precision(self.accountNR)
                self.model.set_precision(precision=self.precision)
                self.model.set_learning_rate(lr)
                self.model.set_weights(global_weights)
                self.model.set_bias(global_bias)
                self.batchSize=self.blockChainConnection.get_BatchSize(self.accountNR)
                while(self.data.curr_batch is None):
                    pass
                while(self.data.curr_batch.size < self.batchSize):
                    pass
                self.data.set_batchSize(self.batchSize)
                x_train, y_train = self.data.generate_batch()
                tt = time.time()
                try:
                    self.model.process_Batch(x_train, y_train)
                except Exception as e:
                    print(f"{self.accountNR}, {self.deviceName}, round: ", self.round, "error; ", e)
                self.analytics.add_round_training_local_time(self.round,time.time()-tt)
                self.analytics.add_round_score(self.round,self.model.test_model())
                self.analytics.add_round_classification_report(self.round,self.model.get_classification_report())
                w = self.model.get_weights()
                b = self.model.get_bias()
                if self.config["DEFAULT"]["PerformProof"]:
                    tp = time.time()
                    self.__generate_Proof(global_weights, global_bias, w, b, self.model.x_train, self.model.y_train, lr)
                    #print(f"{self.accountNR}, {self.deviceName} generated proof: " , self.proof, sep=" ")
                    self.analytics.add_round_proof_times(self.round, time.time() - tp)
                self.model.reset_batch()
                thread=threading.Thread(target=self.update,args=[w,b, self.proof, self.round, balance])
                thread.start()
                print(f"{self.deviceName}:Round {self.round} update took {time.time()-t} seconds")
                print(f"{self.accountNR}, {self.deviceName}, round: ", self.round, "th end ******")
                self.round+=1
                self.analytics.add_round_time(self.round,time.time()-t)
            time.sleep(self.config["DEFAULT"]["WaitingTime"])
                #self.__sleep_call(10)
        self.analytics.write_data()

    def __sleep_call(self, t):
        #print(f"{self.deviceName}:Checking for new update round in:")
        for i in range(0,t):
            #print(i+1,end=" ")
            #print("... ",end=" ")
            time.sleep(1)
        #print()
        #print(f"{self.deviceName}:Checking for new update =>")

def callback(ch, method, properties, body, args):
    data=args
    if isinstance(data, Data):
        batch=pd.read_csv(io.BytesIO(body),header=0,index_col=0)
        data.add_data_to_current_batch(batch)


