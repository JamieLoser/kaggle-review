"""
pandas database for data exploration and fast reloading
based on: https://github.com/colinmorris/instacart-basket-prediction/blob/master/preprocessing/basket_db.py
"""
import pandas as pd
import numpy as np
import os
import gc
from utils.utils import print_mem_time 
from collections import namedtuple

class pd_DB(object):
    def __init__(self):
        self.sp = ','

    def build(self):
        self.Table = namedtuple('Table', 'name fname dtype')
        TABLES = [self.Table(i,"%s/%s"%(self.path,j),None) for i,j in zip(self.names,self.fnames)]
        self._build(self.flags,TABLES)

    def _build(self,flags,tables=[],prob_dtype=False):
        """
            Input:
              tables: a list of namedtuples,
                which have attributes: name, fname, dtype
                name and fname are strings
                dtype is a {} columna name -> data type
                e.g. 'order_id': numpy.int32
                set tables to [] if only some member functions 
                are needed without loading data
              prob_dtype:
                if True, will detect optimal dtype automatically
                with additional time  
            build a self.data {} fname->pd data frame
        """
        print()
        self.flags = flags
        path = flags.data_path
        data = {}
        for table in tables:
            name = table.name
            fname = table.fname
            dtype = table.dtype
            pname = "%s/%s.pkl"%(path,name.split('/')[-1].split('.')[0])
            if os.path.exists(pname):
                data[name] = pd.read_pickle(pname)
            else:
                print("read %s from raw"%fname)
                if dtype is None and prob_dtype:
                    dtype = self._get_dtype(fname,silent=flags.verbosity<=0)
                data[name] = pd.read_csv(fname,dtype=dtype,sep=self.sp)
                data[name].to_pickle(pname)
            print_mem_time("Loaded {} {}".format(fname.split('/')[-1],data[name].shape))
        self.data = data # no copy, pass the inference
        print()

    def _get_dtype(self,fname,silent=False):
        data = pd.read_csv(fname,sep=self.sp).fillna(0)
        cols = data.columns.values
        dtype = {}
        for col in cols:
            if data[col].dtype == np.float64:
                dtype[col] = np.float32
            elif data[col].dtype == np.int64:
                x = data[col].unique()
                mx = np.max(x)
                mi = np.min(x)
                if -128<mi and mx<127:
                    dtype[col] = np.int8
                elif 0<=mi and mx<256:
                    dtype[col] = np.uint8
                elif -32768<mi and mx< 32767:
                    dtype[col] = np.int16
                elif 0<=mi and mx<65535:
                    dtype[col] = np.uint16
                elif -2147483648<mi and mx< 2147483648:
                    dtype[col] = np.int32
                else:
                    dtype[col] = np.int64
            else:
                dtype[col] = data[col].dtype
        if not silent:
            print("\n {} {} \n".format(fname,dtype))
        with open('%s/dtype.txt'%self.flags.data_path,'a') as fo:
            fo.write("{} {} \n".format(fname,dtype))
        del data
        gc.collect()
        return dtype

    def snoop(self):
        raise NotImplementedError()

    def clear(self):
        del self.data
        gc.collect()
