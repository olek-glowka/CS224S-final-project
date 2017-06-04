from __future__ import division
import time
import argparse
import math
import random
import sys
import time
import logging
from datetime import datetime
import os
# uncomment this line to suppress Tensorflow warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import tensorflow as tf
import numpy as np
from six.moves import xrange as range
from tqdm import tqdm
from tensorflow.python.ops import variable_scope as vs
# from tensorflow.python.ops.nn import rnn_cell, dynamic_rnn, bidirectional_dynamic_rnn
# tf.nn.dynamic_rnn
# tf.contrib.rnn.GRUCell(


class Config(object):
    num_features = 2
    batch_size = 10
    num_epochs = 5
    lr = 1e-4
    max_length = 30
    cell_size = 64

    def __init__(self):
        self.output_path = os.path.join('model','{:%Y%m%d_%H%M%S}'.format(datetime.now()))
        self.model_output = os.path.join(self.output_path, "model.weights")

class OurModel():
    def add_placeholders(self):

        # per item in batch, per syllable, features
        self.inputs_placeholder = tf.placeholder(tf.float32, shape = (self.config.batch_size, self.config.max_length, self.config.num_features), name = 'inputs_placeholder')
        # per item in batch, per syllable, 3 predictions
        self.labels_placeholder = tf.placeholder(tf.float32, shape = (self.config.batch_size, self.config.max_length, 3), name = 'labels_placeholder')
        # per item in batch, number of syllables
        self.seq_lens_placeholder = tf.placeholder(tf.int64, shape = (self.config.batch_size))


        # inputs_placeholder = tf.placeholder(tf.float32, shape = (config.batch_size, config.max_length, config.num_features), name = 'inputs_placeholder')
        # seq_lens_placeholder = tf.placeholder(tf.int64, shape = (config.batch_size))

    def create_feed_dict(self, inputs_batch, labels_batch, seq_lens_batch):
        feed_dict = {
            self.inputs_placeholder: inputs_batch,
            self.seq_lens_placeholder: seq_lens_batch
        } 
        if labels_batch is not None:
            feed_dict[self.labels_placeholder] = labels_batch
        return feed_dict


    def add_prediction_op(self):
        cell = tf.contrib.rnn.BasicLSTMCell(self.config.cell_size)
        # o, h = tf.nn.bidirectional_dynamic_rnn(
        o, h = tf.nn.dynamic_rnn(
                                               cell = cell,
                                               # cell_fw = cell,
                                               # cell_bw = cell,
                                               dtype = tf.float32,
                                               sequence_length = self.seq_lens_placeholder,
                                               inputs = self.inputs_placeholder
                                               )
        # o_fw, o_bw = o
        # h_fw, h_bw = h
        # o = tf.concat(2, (fw_o, bw_o))
        # h = tf.concat(1, (fw_h, bw_h))

        # print self.inputs_placeholder # 5 x 30 x 2
        # print self.seq_lens_placeholder # 5
        # print self.labels_placeholder # 5 x 30 x 3
        # print o # 5 x 30 x 64: batch * length * cell
        # print h # sort of ? x 64?

        o2 = tf.reshape(o, (-1, self.config.cell_size))
        W = tf.get_variable('weight', shape = (self.config.cell_size, 3))
        b = tf.get_variable('bias', shape = (self.config.batch_size * self.config.max_length, 3))
        y = tf.reshape(tf.matmul(o2, W) + b, (self.config.batch_size, self.config.max_length, 3))


        self.pred = y

    def add_loss_op(self):
        # Compute cross entropy for each frame.
        mask = tf.sequence_mask(self.seq_lens_placeholder, self.config.max_length)

        masked_labels = tf.boolean_mask(self.labels_placeholder, mask)
        masked_pred = tf.boolean_mask(self.pred, mask)
        loss = tf.nn.l2_loss(tf.subtract(masked_labels, masked_pred))
        
        self.loss = loss

    def add_training_op(self):
    
        optimizer = tf.train.AdamOptimizer(self.config.lr)
        train_op = optimizer.minimize(self.loss)
        
        self.train_op = train_op

    def add_summary_op(self):
        self.merged_summary_op = tf.summary.merge_all()

    def train_on_batch(self, session, train_inputs_batch, train_labels_batch, train_seq_len_batch):
        feed = self.create_feed_dict(train_inputs_batch, train_labels_batch, train_seq_len_batch)
        # batch_cost, summary = session.run([self.loss, self.merged_summary_op], feed)

        loss, _= session.run([self.loss, self.train_op], feed)

        return loss

    def test_on_batch(self, session, test_inputs_batch, test_labels_batch, test_seq_len_batch):
        feed = self.create_feed_dict(test_inputs_batch, test_labels_batch, test_seq_len_batch)
        loss, = session.run([self.loss], feed)

        return loss


    def __init__(self, config):
        self.config = config
        self.build()

    def build(self):
        self.add_placeholders()
        self.add_prediction_op()
        self.add_loss_op()
        self.add_training_op()



def process_line(line):
    line = line.strip().split(' ')
    line = [float(x) for x in line]
    return line

# force it to be max_feats length, pad teh rest with zeros
def pad(elems, config):
    return np.append(elems, np.zeros((config.max_length, elems.shape[1])), 0)[:config.max_length, :]

def make_batches(config, feats_dir, target_dir):
    inputs = np.array([])
    length = np.array([])

    for feats in os.listdir(feats_dir):
        feats = os.path.join(feats_dir, feats)
        with open(feats) as f:
            elems = np.vstack(process_line(line) for line in f)
        padded_elems = pad(elems, config)

        length = np.append(length, min(elems.shape[0], config.max_length))
        if inputs.shape[0] == 0:
            inputs = np.array([padded_elems])
        else:
            inputs = np.append(inputs, [padded_elems], 0)

    labels = np.array([])
    for f0 in os.listdir(target_dir):
        f0 = os.path.join(target_dir, f0)
        with open(f0) as f:
            elems = np.vstack(process_line(line) for line in f)
        padded_elems = pad(elems, config)

        if labels.shape[0] == 0:
            labels = np.array([padded_elems])
        else:
            labels = np.append(labels, [padded_elems], 0)

    batched_inputs = []
    batched_length = []
    batched_labels = []
    # Subtract so all batches are the same size
    for i in range(0, inputs.shape[0] - config.batch_size, config.batch_size):
        batched_inputs.append(inputs[i:i + config.batch_size])
        batched_length.append(length[i:i + config.batch_size])
        batched_labels.append(labels[i:i + config.batch_size])

    return np.array(batched_inputs), np.array(batched_length), np.array(batched_labels)

def test(feats_dir, target_dir):
    config = Config()


    batched_inputs, batched_length, batched_labels = make_batches(config, feats_dir, target_dir)

    num_batches = len(batched_inputs)
    num_test = int(0.1 * num_batches)
    test_idxs = np.random.choice(num_batches, num_test)
    train_idxs = list(set(range(num_batches)) - set(test_idxs))
    num_train = len(train_idxs)

    train_inputs = batched_inputs[train_idxs]
    train_labels = batched_labels[train_idxs]
    train_length = batched_length[train_idxs]

    test_inputs = batched_inputs[test_idxs]
    test_labels = batched_labels[test_idxs]
    test_length = batched_length[test_idxs]


    with tf.Graph().as_default():
        model = OurModel(config)
        
        init = tf.global_variables_initializer()
        saver = tf.train.Saver()


        with tf.Session() as sess:
            start = time.time()
            sess.run(init)
            # saver.restore(sess, model.config.model_output)

            print 'Model initialized in {:.3f}'.format(time.time() - start)

            global_start = time.time()

            for epoch in range(config.num_epochs):
                train_cost = 0
                test_cost = 0
                start = time.time()

                for batch_idx in tqdm(range(num_train), desc = 'Training'):
                    inputs = train_inputs[batch_idx]
                    labels = train_labels[batch_idx]
                    length = train_length[batch_idx]
                
                    loss = model.train_on_batch(sess, inputs, labels, length)

                    train_cost += loss
                train_cost = train_cost / num_train / config.batch_size

                for batch_idx in tqdm(range(num_test), desc = 'Testing'):
                    inputs = test_inputs[batch_idx]
                    labels = test_labels[batch_idx]
                    length = test_length[batch_idx]
                
                    loss = model.test_on_batch(sess, inputs, labels, length)

                    test_cost += loss
                test_cost = test_cost / num_test / config.batch_size


                print "Epoch {}/{}, train_cost = {:.3f}, test_cost = {:3f} time = {:.3f}".format(epoch + 1, config.num_epochs, train_cost, test_cost, time.time() - start)

if __name__ == '__main__':
    test('../ATrampAbroad/feats', '../ATrampAbroad/f0')


















        