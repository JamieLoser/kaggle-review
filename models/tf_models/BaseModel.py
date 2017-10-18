import tensorflow as tf
import numpy as np
import pandas as pd
import time
from utils.utils import print_mem_time
import os

class BaseModel(object):
    def __init__(self,flags):
        self.flags = flags
        self.global_step = tf.Variable(0, name='global_step',trainable=False)
        self.feed_dict = None
        self.summ_op = None
        self.labels = None
        self.var_list = []
        self.loaded_weights = {}
        self._load()
        self._add_graph_keys()
        self.is_training = tf.placeholder(tf.bool)        

    def _add_graph_keys(self):
        tf.GraphKeys.IMAGES = 'images'
        tf.GraphKeys.SCALARS = 'scalars'
        tf.GraphKeys.WEIGHTS = 'weights'
        tf.GraphKeys.REGULARIZATION_LOSSES = 'regularization_losses'
        tf.GraphKeys.SAVE_TENSORS = "save_tensors"
        tf.GraphKeys.GRADIENTS = "gradients"
        tf.GraphKeys.FEATURE_MAPS = "feature_maps"
        tf.GraphKeys.EMBEDDINGS = "embeddings"

    def _build(self,inputs=None,labels=None):
        # build the self.pred tensor
        raise NotImplementedError()

    def _get_l2_loss(self):
        with tf.name_scope("L2_loss"):
            if self.flags.lambdax:
                lambdax = self.flags.lambdax
            else:
                lambdax = 0
            self.l2loss = lambdax*tf.add_n(tf.get_collection(tf.GraphKeys.REGULARIZATION_LOSSES))

    def show_embedding(self,name,save_model="model.ckpt",meta_path='metadata.tsv'):
        self._build()
        self._write_meta()
        from tensorflow.contrib.tensorboard.plugins import projector
        # Use the same LOG_DIR where you stored your checkpoint.
        with tf.Session() as sess:
            self.sess = sess
            sess.run(tf.global_variables_initializer())
            sess.run(tf.local_variables_initializer())
            summary_writer = tf.summary.FileWriter(self.flags.log_path, sess.graph)
            saver = tf.train.Saver()
            saver.save(sess, os.path.join(self.flags.log_path, save_model), 0)
        # Format: tensorflow/contrib/tensorboard/plugins/projector/projector_config.proto
        config = projector.ProjectorConfig()
        # You can add multiple embeddings. Here we add only one.
        embedding = config.embeddings.add()
        embedding.tensor_name = name
        # Link this tensor to its metadata file (e.g. labels).
        embedding.metadata_path = os.path.join(self.flags.log_path, meta_path)
        # Saves a configuration file that TensorBoard will read during startup.
        projector.visualize_embeddings(summary_writer, config)

    def _write_meta(self):
        raise NotImplementedError()

    def _get_embedding(self, layer_name, inputs, v,m,reuse=False):
        """
            V: vocabulary size
            M: embedding sze
        """
        with tf.variable_scope(layer_name.split('/')[-1], reuse=reuse):
            w = self._get_variable(layer_name, name='w', shape=[v, m])
            c = tf.zeros([1,m])
            w = tf.concat([c,w],axis=0)
            x = tf.nn.embedding_lookup(w, inputs, name='word_vector')  # (N, T, M) or (N, M)
            return x    

    def _get_loss(self,labels):
        # build the self.loss tensor
        # This function could be overwritten

        #print("pred {} label{}".format(self.logit.dtype,labels.dtype))

        with tf.name_scope("Loss"):
            with tf.name_scope("cross_entropy"):
                labels = tf.cast(labels, tf.float32)
                #self.logit = tf.cast(self.logit, tf.float32)
                self.loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=self.logit, labels=labels))
            self._get_l2_loss()
            with tf.name_scope("accuracy"):
                y_label = tf.argmax(labels, 1)
                yp_label = tf.argmax(self.logit, 1)
                correct_pred = tf.equal(yp_label,y_label)
                self.acc = tf.reduce_mean(tf.cast(correct_pred, tf.float32))

        with tf.name_scope("summary"):
            if self.flags.visualize:
                tf.summary.scalar(name='TRAIN_CrossEntropy', tensor=self.loss, collections=[tf.GraphKeys.SCALARS])
                tf.summary.scalar(name='TRAIN_Accuracy', tensor=self.acc, collections=[tf.GraphKeys.SCALARS])

                tf.summary.scalar(name='TRAIN_L2loss', tensor=self.l2loss, collections=[tf.GraphKeys.SCALARS]
)

                if 'acc' in self.flags.visualize:
                    tf.summary.histogram(name='pred', values=yp_label, collections=[tf.GraphKeys.FEATURE_MAPS
])
                    tf.summary.histogram(name='truth', values=y_label, collections=[tf.GraphKeys.FEATURE_MAPS
])
                    for cl in range(self.flags.classes):
                        tf.summary.histogram(name='pred%d'%cl, values=tf.slice(self.logit, [0,cl],[self.flags.batch_size, 1]), collections=[tf.GraphKeys.FEATURE_MAPS])



    def _get_opt(self):
        # build the self.opt_op for training

        self.set_train_var()
        tvars = self.var_list
        self.print_trainable()
        with tf.name_scope("Optimizer"):
            opt = self._get_optx()
            grads = tf.gradients(self.loss+self.l2loss, tvars)
            grads = list(zip(grads, tvars))
            # Op to update all variables according to their gradient
            self.opt_op = opt.apply_gradients(grads_and_vars=grads,global_step = self.global_step)

            if self.flags.visualize and "grad" in self.flags.visualize:
                for grad, var in grads:
                    tf.summary.histogram(var.name + '/gradient', grad, collections=[tf.GraphKeys.GRADIENTS])

    def _get_optx(self):
        if self.flags.opt == 'adam':
            opt = tf.train.AdamOptimizer(learning_rate=self.flags.learning_rate)
        elif self.flags.opt == 'sgd':
            opt = tf.train.GradientDescentOptimizer(learning_rate=self.flags.learning_rate)
        elif self.flags.opt == 'momentum':
            opt = tf.train.MomentumOptimizer(learning_rate=self.flags.learning_rate,
                momentum = self.flags.momentum)
        elif self.flags.opt == 'rmsprop':
            opt = tf.train.RMSPropOptimizer(learning_rate=self.flags.learning_rate)
        else:
            print("unkown opt %s"%self.flags.opt)
            assert 0
        return opt

    def _get_summary(self):
        # build the self.summ_op for tensorboard
        # This function could be overwritten
        if not self.flags.visualize or self.flags.visualize=='none':
            return
        summ_collection = "{} {} {} summaries".format(self.flags.comp, self.flags.sol, self.flags.run_name)
        if len(tf.get_collection(tf.GraphKeys.SCALARS)):
            self.scaler_op = tf.summary.merge(tf.get_collection(tf.GraphKeys.SCALARS))
        if len(tf.get_collection(tf.GraphKeys.IMAGES)):
            self.image_op = tf.summary.merge(tf.get_collection(tf.GraphKeys.IMAGES))

        for i in tf.get_collection(tf.GraphKeys.SCALARS):
            tf.add_to_collection(summ_collection, i)
        for i in tf.get_collection(tf.GraphKeys.WEIGHTS):
            tf.add_to_collection(summ_collection, i)
        for i in tf.get_collection(tf.GraphKeys.FEATURE_MAPS):
            tf.add_to_collection(summ_collection, i)
        for i in tf.get_collection(tf.GraphKeys.IMAGES):
            tf.add_to_collection(summ_collection, i)
        for i in tf.get_collection(tf.GraphKeys.GRADIENTS):
            tf.add_to_collection(summ_collection, i)
        for i in tf.get_collection(tf.GraphKeys.EMBEDDINGS):
            tf.add_to_collection(summ_collection, i)
        self.summ_op = tf.summary.merge(tf.get_collection(summ_collection))

    def _feed_dict(self):
        # build the self.feed_dict {}, default None
        # in case some tensors need to be changed during runtime
        raise NotImplementedError()

    def _load(self):
        if self.flags.load_path is not None:
            paths = self.flags.load_path.split(',')
            self.weights = {}
            for path in paths:
                self.weights.update( np.load(path, encoding='latin1').item())
        else:
            self.weights = None

    def _save(self):
        # save weights in .npy format
        # this function could be overwritten
        weights = {}
        tvars = tf.trainable_variables() + tf.get_collection(tf.GraphKeys.SAVE_TENSORS)
        tvars_vals = self.sess.run(tvars)

        for var, val in zip(tvars, tvars_vals):
            weights[var.name] = val

        name = "{}/{}_{}_{}_{}.npy".format(self.flags.save_path, self.flags.task, self.flags.run_name, self.flags.net, self.flags.pre_epochs + int(self.epoch))
        np.save(name, weights)

    def print_all_variables(self):
        tvars = tf.trainable_variables()
        #tvars_vals = self.sess.run(tvars)
        print()
        for var in (tvars):
            print(var.name) 
        print()

    def reset_graph(self):
        tf.reset_default_graph()

    def predict(self,inputs, labels=None, activation="softmax"):

        # This function could be overwritten
        # default implementation is for multi classification
        with open(self.flags.pred_path,'w') as f:
            pass
        print()
        self._build(inputs)
        print()
        if labels is not None:
            self._get_loss(labels)
        self.pred = self._activate(self.logit, activation)

        with tf.Session() as sess:
            self.sess = sess
            start_time = time.time()
            sess.run(tf.global_variables_initializer())
            sess.run(tf.local_variables_initializer())
            self._restore()
            coord = tf.train.Coordinator()
            threads = tf.train.start_queue_runners(coord=coord)
            if self.flags.log_path and self.flags.visualize is not None:
                summary_writer = tf.summary.FileWriter(self.flags.log_path, sess.graph)
            prev = 0
            count = 0
            ave_loss = 0
            try:
                while not coord.should_stop():
                    if labels is None:
                        pred = sess.run([self.pred],feed_dict=self.feed_dict)[0]
                    else:
                        pred,loss = sess.run([self.pred, self.loss],feed_dict=self.feed_dict)
                        ave_loss = ave_loss*0.9 + loss*0.1
                    count+=pred.shape[0]
                    current = count//1000
                    if current>prev:
                        duration = time.time() - start_time
                        if labels is None:
                            print ("%d samples predicted, Time %.3f"%(count, duration))
                        else:
                            print ("%d samples predicted, Time %.3f, loss %.3f"%(count, duration, ave_loss))
                        prev = current
                    with open(self.flags.pred_path,'a') as f:
                        pd.DataFrame(pred).to_csv(f, header=False,index=False, float_format='%.5f')
            except tf.errors.OutOfRangeError:
                duration = time.time() - start_time
                print ("Total time: %.3f"%duration)
            finally:
                coord.request_stop()
            coord.join(threads)


    def train(self,inputs,labels, samples = None, build_with_labels=False):

        # This function could be overwritten
        # default implementation is for multi classification

        if samples is not None:
            self.flags.total_samples = samples
        print()
        if build_with_labels:
            self._build(inputs,labels)
        else:
            self._build(inputs)
        print()
        self._get_loss(labels)
        self._get_opt()
        self._get_summary()

        ave_loss = 0
        ave_acc = 0
        count = 0
        self.epoch = 0
        self.total_batch = self.flags.epochs*self.flags.total_samples//self.flags.batch_size
        print("Training for %d epochs %d batchs"%(self.flags.epochs, self.total_batch))

        with tf.Session() as sess:
            self.sess = sess
            start_time = time.time()
            sess.run(tf.global_variables_initializer())
            sess.run(tf.local_variables_initializer())
            self._restore()
            #self.print_all_variables()
            coord = tf.train.Coordinator()
            threads = tf.train.start_queue_runners(coord=coord)
            if self.flags.log_path:
                summary_writer = tf.summary.FileWriter(self.flags.log_path, sess.graph)
            try:
                while not coord.should_stop():
                    if self.summ_op is None or self.flags.log_path is None:
                        loss,acc,_,step,y = sess.run([self.loss, self.acc, self.opt_op, self.global_step,labels
],feed_dict=self.feed_dict)
                    else:
                        loss,acc,_,step,summary,y = sess.run([self.loss, self.acc, self.opt_op, self.global_step, 
                            self.summ_op, labels],feed_dict=self.feed_dict)
                        summary_writer.add_summary(summary, step)

                    #print(y)
                    if count==0:
                        ave_loss = loss
                        ave_acc = acc
                        print("First loss %.3f"%loss)
                    else:
                        ave_loss = ave_loss*0.9 + loss*0.1
                        ave_acc = ave_acc*0.9 + acc*0.1

                    count += self.flags.batch_size
                    if count//self.flags.total_samples > self.epoch:
                        duration = time.time() - start_time
                        self.epoch = count//self.flags.total_samples
                        print("Epochs: %d Training Loss: %.4f %s: %.4f Time: %.3f s "%(self.epoch, ave_loss, 
                            self.flags.metric, ave_acc, duration))
                        if self.epoch%self.flags.save_epochs == 0:
                            self._save()
                    if count%(self.flags.batch_size*10) == 0:
                        duration = time.time() - start_time
                        print("Samples: %d Training Loss: %.4f %s: %.4f Time: %.3f s "%(count, ave_loss, 
                            self.flags.metric, ave_acc, duration))
            except tf.errors.OutOfRangeError:
                duration = time.time() - start_time
                print("Epochs: %d Training Loss: %.4f %s: %.4f Time: %.3f s"%(self.flags.epochs, ave_loss, self.flags.metric, ave_acc, duration))
                self.epoch = self.flags.epochs
                self._save()
            finally:
                coord.request_stop()
            coord.join(threads)
            duration = time.time() - start_time
            print("Total time: %.4f"%duration)

    def _xavi_uniform(self, fan_in,fan_out):
        # return a upper/lower bound
        return np.sqrt(6. / (fan_in + fan_out))

    def _xavi_norm(self, fan_in,fan_out):
        # return a std
        return np.sqrt(2. / (fan_in + fan_out))

    def _fc(self, x, fan_in, fan_out, layer_name, activation=None, L2=1, use_bias=True):
        show_weight = self.flags.visualize and 'weight' in self.flags.visualize
        with tf.variable_scope(layer_name.split('/')[-1]):
            w,b = self._get_fc_weights(fan_in, fan_out, layer_name)
            net = tf.matmul(x,w)
            if use_bias:
                net = tf.nn.bias_add(net, b)
            net = self._activate(net, activation)
            if show_weight:
                tf.summary.histogram(name='W', values=w, collections=[tf.GraphKeys.WEIGHTS])
                if use_bias:
                    tf.summary.histogram(name='bias', values=b, collections=[tf.GraphKeys.WEIGHTS])
        return net


    def _get_fc_weights(self, fan_in, fan_out, layer_name):
        w1 = self._get_variable(layer_name, name='weights', shape=[fan_in,fan_out])
        b1 = self._get_variable(layer_name, name='bias', shape=[fan_out])
        return w1,b1

    def _batch_normalization(self, x, layer_name, eps=0.001):
        with tf.variable_scope(layer_name.split('/')[-1]):
            beta, gamma, mean, variance = self._get_batch_normalization_weights(layer_name)
            # beta, gamma, mean, variance are numpy arrays!!!

            if beta is None:
                try:
                    net = tf.layers.batch_normalization(x, epsilon = eps)
                except:
                    net = tf.nn.batch_normalization(x, 0, 1, 0, 1, 0.01)
            else:
                try:
                    net = tf.layers.batch_normalization(x, epsilon = eps,        
                        beta_initializer = tf.constant_initializer(value=beta,dtype=tf.float32),
                        gamma_initializer = tf.constant_initializer(value=gamma,dtype=tf.float32),
                        moving_mean_initializer = tf.constant_initializer(value=mean,dtype=tf.float32),
                        moving_variance_initializer = tf.constant_initializer(value=variance,dtype=tf.float32), 
                    )
                except:
                    net = tf.nn.batch_normalization(x, mean, variance, beta, gamma, 0.01)
        mean = '%s/batch_normalization/moving_mean:0'%(layer_name)
        variance = '%s/batch_normalization/moving_variance:0'%(layer_name)
        try:
            tf.add_to_collection(tf.GraphKeys.SAVE_TENSORS, tf.get_default_graph().get_tensor_by_name(mean))
            tf.add_to_collection(tf.GraphKeys.SAVE_TENSORS, tf.get_default_graph().get_tensor_by_name(variance))
        except:
            pass
        return net

    def _get_batch_normalization_weights(self,layer_name):
        beta = '%s/batch_normalization/beta:0'%(layer_name)
        gamma = '%s/batch_normalization/gamma:0'%(layer_name)
        mean = '%s/batch_normalization/moving_mean:0'%(layer_name)
        variance = '%s/batch_normalization/moving_variance:0'%(layer_name)
        if self.weights is None or beta not in self.weights:
            print('{:>23} {:>23}'.format(beta, 'using default initializer'))
            return None, None, None, None
        else:
            betax = self.weights[beta]
            gammax = self.weights[gamma]
            meanx = self.weights[mean]
            variancex = self.weights[variance]

            self.loaded_weights[beta]=1
            self.loaded_weights[gamma]=1
            self.loaded_weights[mean]=1
            self.loaded_weights[variance]=1
            #print('{:>23} {:>23}'.format(beta, 'load from %s'%self.flags.load_path))
            return betax,gammax,meanx,variancex

    def _reshape_tensors(self, x, y):
        """
        Input:
            x: input tensor
            y: the tensor to be matched
            NHWC
            reshape x so that Hx==Hy and Wx==Wy
        """
        Hx,Wx,Cx = x.get_shape().as_list()[1:]
        Hy,Wy,Cy = y.get_shape().as_list()[1:]


    def _activate(self, net, activation):
        if activation=="relu":
            net = tf.nn.relu(net)
        elif activation == 'leaky':
            net = self._leaky(net, alpha = 0.1)
        elif activation == "sigmoid":
            net = tf.nn.sigmoid(net)
        elif activation == "softmax":
            net = tf.nn.softmax(net)
        elif activation == "elu":
            net = tf.nn.elu(net)
        return net


    def _leaky(self, x, alpha):
        with tf.name_scope("leaky_relu"):
            m_x = tf.nn.relu(-x)
            x = tf.nn.relu(x)
            x -= alpha * m_x
        return x

    def _getN(self, s,n):
        a = [s for i in range(n)]
        return a

    def _logloss(self, y, yp):
        #return tf.losses.log_loss(labels=y,predictions=yp)
        yp = tf.maximum(0.0001, yp)
        yp = tf.minimum(0.9999, yp)
        return -y*tf.log(yp)-(1-y)*tf.log(1-yp)

    def _get_variable(self, layer_name, name, shape):
        if len(shape)>1:
            return self._get_weight_variable(layer_name, name, shape)
        else:
            return self._get_bias_variable(layer_name, name, shape)

    def _get_weight_variable(self, layer_name, name, shape, L2=1):
        wname = '%s/%s:0'%(layer_name,name)
        fanin, fanout = shape[-2:]
        for dim in shape[:-2]:
            fanin *= float(dim)
            fanout *= float(dim)

        sigma = self._xavi_norm(fanin, fanout)
        if self.weights is None or wname not in self.weights:
            w1 = tf.get_variable(name,initializer=tf.truncated_normal(shape = shape,
                mean=0,stddev = sigma))
            print('{:>23} {:>23}'.format(wname, 'randomly initialize'))
        else:
            w1 = tf.get_variable(name, shape = shape,
                initializer=tf.constant_initializer(value=self.weights[wname],dtype=tf.float32))
            self.loaded_weights[wname]=1
        if wname != w1.name:
            print(wname,w1.name)
            assert False
        tf.add_to_collection(tf.GraphKeys.REGULARIZATION_LOSSES, tf.nn.l2_loss(w1)*L2)
        return w1

    def _get_bias_variable(self, layer_name, name, shape, L2=1):
        bname = '%s/%s:0'%(layer_name,name)

        if self.weights is None or bname not in self.weights:
            b1 = tf.get_variable(name,shape=shape,initializer=tf.constant_initializer(0.01))
            print('{:>23} {:>23}'.format(bname, 'randomly initialize'))
        else:
            b1 = tf.get_variable(name,shape=shape,initializer=tf.constant_initializer(value=self.weights[bname],dtype=tf.float32))
            self.loaded_weights[bname]=1
            #print('{:>23} {:>23}'.format(wname, 'load from %s'%self.flags.load_path))
        if bname != b1.name:
            print(bname,b1.name)
            assert False
        tf.add_to_collection(tf.GraphKeys.REGULARIZATION_LOSSES, tf.nn.l2_loss(b1)*L2)
        return b1

    def _restore(self,only_once=True):
        var_list = tf.trainable_variables()
        for var in var_list:
            if self.weights and var.name in self.weights:
                if only_once and self.loaded_weights and var.name in self.loaded_weights:
                    continue 
                          
                assign_op = var.assign(self.weights[var.name])
                self.sess.run(assign_op)
                self.loaded_weights[var.name] = 1
                #if only_once:
                print("restore %s"%var.name)

    def set_train_var(self):
        # This function could be overwritten
        self.var_list = tf.trainable_variables() 

    def print_trainable(self):
        tvars = self.var_list
        print("\nvariables to train")
        vv = sorted(list(set(["{}".format(i.name.split('/')[:2]) for i in tvars])))
        for i in vv:
            print(i)
        print()

    def _mse(self, x, y):
        return tf.reduce_mean(tf.square(x-y))

    def _get_acc_loss(self,aloss,loss,ratio=0.9):
        if aloss == 0:
            return loss
        else:
            return aloss*ratio + loss*(1-ratio)

    def just_graph_with_input(self,inputs):
        self._build(inputs)

        with tf.Session() as sess:
            self.sess = sess
            sess.run(tf.global_variables_initializer())
            sess.run(tf.local_variables_initializer())
            start = time.time()
            if self.flags.log_path:
                summary_writer = tf.summary.FileWriter(self.flags.log_path, sess.graph)

    def _batch_gen(self):
        raise NotImplementedError()

    def _batch_gen_va(self):
        raise NotImplementedError()

    def _batch_gen_test(self):
        raise NotImplementedError()

    def predict_from_placeholder(self,activation=None):
        self._build()
        self._get_summary()
        if activation is not None:
            self.logit = self._activate(self.logit,activation)
        with open(self.flags.pred_path,'w') as f:
            pass
        count = 0
        with tf.Session() as sess:
            self.sess = sess
            sess.run(tf.global_variables_initializer())
            sess.run(tf.local_variables_initializer())
            if self.flags.log_path and self.flags.visualize is not None:
                summary_writer = tf.summary.FileWriter(self.flags.log_path, sess.graph)
            for batch in self._batch_gen_test():
                x,_,epoch = batch
                if self.flags.log_path and self.flags.visualize is not None:
                    summary,pred = sess.run([self.summ_op,self.logit],feed_dict={self.inputs:x,self.is_training:0})
                    summary_writer.add_summary(summary, count)
                else:
                    pred = sess.run(self.logit,feed_dict={self.inputs:x,self.is_training:0})
                count+=1
                if count%self.flags.verbosity == 0:
                    print_mem_time("Epoch %d Batch %d "%(epoch,count))
                self.write_pred(pred)

    def write_pred(self,pred):
        with open(self.flags.pred_path,'a') as f:
            pd.DataFrame(pred).to_csv(f, header=False,index=False, float_format='%.5f')

    def train_from_placeholder(self, va=False):

        if self.labels is None:
            self.labels = tf.placeholder(tf.float32, shape=(None,None))
        self._build()
        self._get_loss(self.labels)
        self._get_opt()
        self._get_summary()
        ve = self.flags.verbosity

        with tf.Session() as sess:
            self.sess = sess
            sess.run(tf.global_variables_initializer())
            sess.run(tf.local_variables_initializer())
            self._restore()
            if self.flags.log_path and self.flags.visualize is not None:
                self.summary_writer = tf.summary.FileWriter(self.flags.log_path, sess.graph)
            count = 0
            ave_loss = 0
            self.epoch = 0
            for batch in self._batch_gen():
                x,y,epoch = batch
                loss = self._run_train(x,y)
                if count==0:
                    print("First loss",loss)
                count+=1
                ave_loss = self._update_ave_loss(ave_loss,loss)
                if count%(ve//10) == 0:
                    print_mem_time("Epoch %d Batch %d ave loss %.3f"%(epoch,count,ave_loss))
                if va and count%ve == 0:
                    self.eval_va()
                if epoch>self.epoch:
                    self.epoch = epoch
                    if epoch%self.flags.save_epochs==0:
                        self._save()
            self.epoch = self.flags.epochs
            self._save()

    def _run_train(self,x,y):
        if self.flags.log_path and self.flags.visualize is not None:
            summary,_,loss = self.sess.run([self.summ_op,self.opt_op,self.loss],feed_dict={self.inputs:x,self.labels:y,self.is_training:1})
            self.summary_writer.add_summary(summary, count)
        else:
            _,loss = self.sess.run([self.opt_op,self.loss],feed_dict={self.inputs:x,self.labels:y,self.is_training:1})
        return loss

    def eval_va(self):
        losses = []
        for x,y,_  in self._batch_gen_va():
            loss,logit = self.sess.run([self.loss,self.logit],feed_dict={self.inputs:x,self.labels:y,self.is_training:0})
            #print_mem_time("Validation loss %.3f"%(loss))
            losses.append(loss)
        print("Ave validation loss {}".format(np.mean(losses)))

                 
    def _update_ave_loss(self,ave_loss,loss):
        if ave_loss == 0:
            return loss
        return ave_loss*0.99 + loss*0.01

    def _dropout(self,x,keep_prob = None):
        if keep_prob is None:
            keep_prob = self.flags.keep_prob
        return tf.cond(self.is_training, lambda: tf.nn.dropout(x, keep_prob), lambda: x)
