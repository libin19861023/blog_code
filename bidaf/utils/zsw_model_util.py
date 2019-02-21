import tensorflow as tf
from tensorflow.python.util import nest
from  utils.general import flatten,reconstruct,add_wd,exp_mask
from tensorflow.python.ops.rnn import  bidirectional_dynamic_rnn as _bidirectional_dynamic_rnn

def dropout(x, keep_prob, noise_shape=None, seed=None, name=None):
    with tf.name_scope(name or "dropout"):
      #  if keep_prob < 1.0:
       #   d = tf.nn.dropout(x, keep_prob, noise_shape=noise_shape, seed=seed)
        #  out = d
         # return out
        x = tf.cond(keep_prob<1.0,lambda:tf.nn.dropout(x, keep_prob, noise_shape=noise_shape, seed=seed),lambda:x)
        return x


def conv1d(in_, filter_size, height, padding,  keep_prob=1.0, scope=None):
    with tf.variable_scope(scope or "conv1d"):
        num_channels = in_.get_shape()[-1]
        filter_ = tf.get_variable("filter", shape=[1,height, num_channels, filter_size], dtype='float')
        bias = tf.get_variable("bias", shape=[filter_size], dtype='float')
        strides = [1,1, 1 ,1]
        #if keep_prob < 1.0:
        print ("in_:{}".format(in_))
        in_ = dropout(in_, keep_prob)
        print("in_ dropout:{}".format(in_))
        xxc = tf.nn.conv2d(in_, filter_, strides, padding) + bias  # [N, JX, W/filter_stride, filter_size]
        out = tf.reduce_max(tf.nn.relu(xxc),2)  # [N, JX, d]
        return out

def multi_conv1d(in_, filter_sizes, heights, padding, keep_prob=1.0, scope=None):
    with tf.variable_scope(scope or "multi_conv1d"):
        assert len(filter_sizes) == len(heights)
        outs = []
        for filter_size, height in zip(filter_sizes, heights):
            if filter_size == 0:
                continue
            out = conv1d(in_, filter_size, height, padding,  keep_prob=keep_prob, scope="conv1d_{}".format(height))
            outs.append(out)
        concat_out = tf.concat(outs,2)

        return concat_out



def highway_layer(arg, bias, bias_start=0.0, scope=None, wd=0.0, input_keep_prob=1.0, ):
    with tf.variable_scope(scope or "highway_layer"):
        d = arg.get_shape()[-1]
        trans = linear([arg], d, bias, bias_start=bias_start, scope='trans', wd=wd, input_keep_prob=input_keep_prob)
        trans = tf.nn.relu(trans)
        gate = linear([arg], d, bias, bias_start=bias_start, scope='gate', wd=wd, input_keep_prob=input_keep_prob)  ###这里可以尝试把b设置成负数
        gate = tf.nn.sigmoid(gate)
        out = gate * trans + (1 - gate) * arg
        return out


def highway_network(arg, num_layers, bias, bias_start=0.0, scope=None, wd=0.0, input_keep_prob=1.0):
    with tf.variable_scope(scope or "highway_network"):
        prev = arg
        cur = None
        for layer_idx in range(num_layers):
            cur = highway_layer(prev, bias, bias_start=bias_start, scope="layer_{}".format(layer_idx), wd=wd,
                                input_keep_prob=input_keep_prob)
            prev = cur
        return cur
def _linear(args, output_size, bias, bias_start=0.0, scope=None):
  """Linear map: sum_i(args[i] * W[i]), where W[i] is a variable.

  Args:
    args: a 2D Tensor or a list of 2D, batch x n, Tensors.
    output_size: int, second dimension of W[i].
    bias: boolean, whether to add a bias term or not.
    bias_start: starting value to initialize the bias; 0 by default.
    scope: VariableScope for the created subgraph; defaults to "Linear".

  Returns:
    A 2D Tensor with shape [batch x output_size] equal to
    sum_i(args[i] * W[i]), where W[i]s are newly created matrices.

  Raises:
    ValueError: if some of the arguments has unspecified or wrong shape.
  """
  from tensorflow.python.ops import variable_scope as vs
  from tensorflow.python.ops import math_ops
  from tensorflow.python.ops import array_ops
  from tensorflow.python.ops import init_ops


  if args is None or (nest.is_sequence(args) and not args):
    raise ValueError("`args` must be specified")
  if not nest.is_sequence(args):
    args = [args]

  # Calculate the total size of arguments on dimension 1.
  total_arg_size = 0
  shapes = [a.get_shape().as_list() for a in args]
  for shape in shapes:
    if len(shape) != 2:
      raise ValueError("Linear is expecting 2D arguments: %s" % str(shapes))
    if not shape[1]:
      raise ValueError("Linear expects shape[1] of arguments: %s" % str(shapes))
    else:
      total_arg_size += shape[1]

  dtype = [a.dtype for a in args][0]

  # Now the computation.
  with vs.variable_scope(scope or "Linear"):
    matrix = vs.get_variable(
        "Matrix", [total_arg_size, output_size], dtype=dtype)
    if len(args) == 1:
      res = math_ops.matmul(args[0], matrix)
    else:
      res = math_ops.matmul(array_ops.concat(1, args), matrix)
    if not bias:
      return res
    bias_term = vs.get_variable(
        "Bias", [output_size],
        dtype=dtype,
        initializer=init_ops.constant_initializer(
            bias_start, dtype=dtype))
  return res + bias_term


def linear(args, output_size, bias, bias_start=0.0, scope=None, squeeze=False, wd=0.0, input_keep_prob=1.0):
    if args is None or (nest.is_sequence(args) and not args):
        raise ValueError("`args` must be specified")
    if not nest.is_sequence(args):
        args = [args]

    flat_args = [flatten(arg, 1) for arg in args]
    #if input_keep_prob < 1.0:   ###############################!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    flat_args = [ tf.nn.dropout(arg, input_keep_prob) for arg in flat_args]
    #flat_out = _linear(flat_args, output_size, bias, bias_start=bias_start, scope=scope)
    flat_out = tf.layers.dense(flat_args[0], output_size, use_bias=bias)
    out = reconstruct(flat_out, args[0], 1)
    if squeeze:
        out = tf.squeeze(out, [len(args[0].get_shape().as_list())-1])
    if wd:
        add_wd(wd)

    return out


def bidirectional_dynamic_rnn(cell_fw, cell_bw, inputs, sequence_length=None,
                              initial_state_fw=None, initial_state_bw=None,
                              dtype=None, parallel_iterations=None,
                              swap_memory=False, time_major=False, scope=None):
    assert not time_major

    flat_inputs = flatten(inputs, 2)  # [-1, J, d]
    #flat_inputs = flatten2(inputs)  # [-1, J, d]
    #tmpshape = tf.shape(inputs)
   # flat_inputs = tf.reshape(inputs,(tmpshape[0],-1,tmpshape[-1]))
    #flat_inputs = tf.reshape(inputs, (tmpshape[0], , tmpshape[len(tmpshape)-1]))
    flat_len = None if sequence_length is None else tf.cast(flatten(sequence_length, 0), 'int64')
    print ("inputs==={}   |||   flat_inputs==={}  |||  flat_len:{}".format(inputs,flat_inputs,flat_len))
    # (flat_fw_outputs, flat_bw_outputs), final_state = \
    #     tf.nn.bidirectional_dynamic_rnn(cell_fw, cell_bw, flat_inputs, sequence_length=flat_len,
    #                                initial_state_fw=initial_state_fw, initial_state_bw=initial_state_bw,
    #                                dtype=dtype, parallel_iterations=parallel_iterations, swap_memory=swap_memory,
    #                                time_major=time_major, scope=scope)
    (flat_fw_outputs, flat_bw_outputs), final_state = \
        _bidirectional_dynamic_rnn(cell_fw, cell_bw, flat_inputs, sequence_length=flat_len,
                                   initial_state_fw=initial_state_fw, initial_state_bw=initial_state_bw,
                                   dtype=dtype, parallel_iterations=parallel_iterations, swap_memory=swap_memory,
                                   time_major=time_major, scope=scope)
    fw_outputs = reconstruct(flat_fw_outputs, inputs, 2)
    bw_outputs = reconstruct(flat_bw_outputs, inputs, 2)
    # FIXME : final state is not reshaped!
    return (fw_outputs, bw_outputs), final_state



######attention


def attention_layer(logit_func, wd ,  h, u, h_mask=None, u_mask=None, scope=None, tensor_dict=None):
    with tf.variable_scope(scope or "attention_layer"):
        u_a, h_a = bi_attention(logit_func,wd, h, u, h_mask=h_mask, u_mask=u_mask, tensor_dict=tensor_dict)
        p0 = tf.concat([h, u_a, h * u_a, h * h_a], 3)
        return p0
        # if config.q2c_att or config.c2q_att:
        #     u_a, h_a = bi_attention(config, is_train, h, u, h_mask=h_mask, u_mask=u_mask, tensor_dict=tensor_dict)
        # if not config.c2q_att:
        #     JX = tf.shape(h)[2]
        #     M = tf.shape(h)[1]
        #     JQ = tf.shape(u)[1]
        #     u_a = tf.tile(tf.expand_dims(tf.expand_dims(tf.reduce_mean(u, 1), 1), 1), [1, M, JX, 1])
        # if config.q2c_att:
        #     p0 = tf.concat([h, u_a, h * u_a, h * h_a], 3)
        #     # p0 = tf.concat(3, [h, u_a, h * u_a, h * h_a])
        # else:
        #     p0 = tf.concat([h, u_a, h * u_a], 3)
        #     # p0 = tf.concat(3, [h, u_a, h * u_a])
        # return p0


def bi_attention(logit_func,wd,  h, u, h_mask=None, u_mask=None, scope=None, tensor_dict=None):
    with tf.variable_scope(scope or "bi_attention"):
        JX = tf.shape(h)[2]
        M = tf.shape(h)[1]
        JQ = tf.shape(u)[1]
        h_aug = tf.tile(tf.expand_dims(h, 3), [1, 1, 1, JQ, 1])
        u_aug = tf.tile(tf.expand_dims(tf.expand_dims(u, 1), 1), [1, M, JX, 1, 1])
        if h_mask is None:
            hu_mask = None
        else:
            h_mask_aug = tf.tile(tf.expand_dims(h_mask, 3), [1, 1, 1, JQ])
            u_mask_aug = tf.tile(tf.expand_dims(tf.expand_dims(u_mask, 1), 1), [1, M, JX, 1])
            hu_mask = h_mask_aug & u_mask_aug

        u_logits = get_logits([h_aug, u_aug], None, True, wd=wd, mask=hu_mask,
                               func=logit_func, scope='u_logits')  # [N, M, JX, JQ]
        u_a = softsel(u_aug, u_logits)  # [N, M, JX, d]
        h_a = softsel(h, tf.reduce_max(u_logits, 3))  # [N, M, d]
        h_a = tf.tile(tf.expand_dims(h_a, 2), [1, 1, JX, 1])

        if tensor_dict is not None:
            a_u = tf.nn.softmax(u_logits)  # [N, M, JX, JQ]
            a_h = tf.nn.softmax(tf.reduce_max(u_logits, 3))
            tensor_dict['a_u'] = a_u
            tensor_dict['a_h'] = a_h
            variables = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope=tf.get_variable_scope().name)
            for var in variables:
                tensor_dict[var.name] = var

        return u_a, h_a



def get_logits(args, size, bias, bias_start=0.0, scope=None, mask=None, wd=0.0, input_keep_prob=1.0, func=None):
    # if func is None:
    #     func = "sum"
    # if func == 'sum':
    #     return sum_logits(args, mask=mask, name=scope)
    # elif func == 'linear':
    #     return linear_logits(args, bias, bias_start=bias_start, scope=scope, mask=mask, wd=wd, input_keep_prob=input_keep_prob,
    #                          is_train=is_train)
    # elif func == 'double':
    #     return double_linear_logits(args, size, bias, bias_start=bias_start, scope=scope, mask=mask, wd=wd, input_keep_prob=input_keep_prob,
    #                                 is_train=is_train)
    # elif func == 'dot':
    #     assert len(args) == 2
    #     arg = args[0] * args[1]
    #     return sum_logits([arg], mask=mask, name=scope)
    # elif func == 'mul_linear':
    #     assert len(args) == 2
    #     arg = args[0] * args[1]
    #     return linear_logits([arg], bias, bias_start=bias_start, scope=scope, mask=mask, wd=wd, input_keep_prob=input_keep_prob,
    #                          is_train=is_train)
    # elif func == 'proj':
    #     assert len(args) == 2
    #     d = args[1].get_shape()[-1]
    #     proj = linear([args[0]], d, False, bias_start=bias_start, scope=scope, wd=wd, input_keep_prob=input_keep_prob,
    #                   is_train=is_train)
    #     return sum_logits([proj * args[1]], mask=mask)
    # elif func == 'tri_linear':
    #     assert len(args) == 2
    #     new_arg = args[0] * args[1]
    #     return linear_logits([args[0], args[1], new_arg], bias, bias_start=bias_start, scope=scope, mask=mask, wd=wd, input_keep_prob=input_keep_prob,
    #                          is_train=is_train)
    # else:
    #     raise Exception()

    if func == "tri_linear":
        assert len(args) == 2
        new_arg = args[0] * args[1]
        return linear_logits([args[0], args[1], new_arg], bias, bias_start=bias_start, scope=scope, mask=mask, wd=wd,
                             input_keep_prob=input_keep_prob,
                             )



def softsel(target, logits, mask=None, scope=None):
    """

    :param target: [ ..., J, d] dtype=float
    :param logits: [ ..., J], dtype=float
    :param mask: [ ..., J], dtype=bool
    :param scope:
    :return: [..., d], dtype=float
    """
    with tf.name_scope(scope or "Softsel"):
        a = softmax(logits, mask=mask)
        target_rank = len(target.get_shape().as_list())
        out = tf.reduce_sum(tf.expand_dims(a, -1) * target, target_rank - 2)
        return out


def softmax(logits, mask=None, scope=None):
    with tf.name_scope(scope or "Softmax"):
        if mask is not None:
            logits = exp_mask(logits, mask)
        flat_logits = flatten(logits, 1)
        flat_out = tf.nn.softmax(flat_logits)
        out = reconstruct(flat_out, logits, 1)

        return out


def linear_logits(args, bias, bias_start=0.0, scope=None, mask=None, wd=0.0, input_keep_prob=1.0):
    with tf.variable_scope(scope or "Linear_Logits"):
        logits = linear(args, 1, bias, bias_start=bias_start, squeeze=True, scope='first',
                        wd=wd, input_keep_prob=input_keep_prob)
        if mask is not None:
            logits = exp_mask(logits, mask)
        return logits


import math
from tensorflow.python.framework import constant_op
from tensorflow.python.framework import ops
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.ops import math_ops


def cosine_decay_restarts(learning_rate,
                          global_step,
                          first_decay_steps,
                          t_mul=2.0,
                          m_mul=1.0,
                          alpha=0.0,
                          name=None):
  """Applies cosine decay with restarts to the learning rate.

  See [Loshchilov & Hutter, ICLR2016], SGDR: Stochastic Gradient Descent
  with Warm Restarts. https://arxiv.org/abs/1608.03983

  When training a model, it is often recommended to lower the learning rate as
  the training progresses.  This function applies a cosine decay function with
  restarts to a provided initial learning rate.  It requires a `global_step`
  value to compute the decayed learning rate.  You can just pass a TensorFlow
  variable that you increment at each training step.

  The function returns the decayed learning rate while taking into account
  possible warm restarts. The learning rate multiplier first decays
  from 1 to `alpha` for `first_decay_steps` steps. Then, a warm
  restart is performed. Each new warm restart runs for `t_mul` times more steps
  and with `m_mul` times smaller initial learning rate.

  Example usage:
  ```python
  first_decay_steps = 1000
  lr_decayed = cosine_decay_restarts(learning_rate, global_step,
                                     first_decay_steps)
  ```

  Args:
    learning_rate: A scalar `float32` or `float64` Tensor or a Python number.
      The initial learning rate.
    global_step: A scalar `int32` or `int64` `Tensor` or a Python number.
      Global step to use for the decay computation.
    first_decay_steps: A scalar `int32` or `int64` `Tensor` or a Python number.
      Number of steps to decay over.
    t_mul: A scalar `float32` or `float64` `Tensor` or a Python number.
      Used to derive the number of iterations in the i-th period
    m_mul: A scalar `float32` or `float64` `Tensor` or a Python number.
      Used to derive the initial learning rate of the i-th period:
    alpha: A scalar `float32` or `float64` Tensor or a Python number.
      Minimum learning rate value as a fraction of the learning_rate.
    name: String. Optional name of the operation.  Defaults to 'SGDRDecay'.
  Returns:
    A scalar `Tensor` of the same type as `learning_rate`.  The decayed
    learning rate.
  Raises:
    ValueError: if `global_step` is not supplied.
  """
  if global_step is None:
    raise ValueError("cosine decay restarts requires global_step")
  with ops.name_scope(name, "SGDRDecay", [learning_rate, global_step]) as name:
    learning_rate = ops.convert_to_tensor(
        learning_rate, name="initial_learning_rate")
    dtype = learning_rate.dtype
    global_step = math_ops.cast(global_step, dtype)
    first_decay_steps = math_ops.cast(first_decay_steps, dtype)
    alpha = math_ops.cast(alpha, dtype)
    t_mul = math_ops.cast(t_mul, dtype)
    m_mul = math_ops.cast(m_mul, dtype)

    completed_fraction = global_step / first_decay_steps

    def compute_step(completed_fraction, geometric=False):
      if geometric:
        i_restart = math_ops.floor(
            math_ops.log(1.0 - completed_fraction * (1.0 - t_mul)) /
            math_ops.log(t_mul))

        sum_r = (1.0 - t_mul**i_restart) / (1.0 - t_mul)
        completed_fraction = (completed_fraction - sum_r) / t_mul**i_restart

      else:
        i_restart = math_ops.floor(completed_fraction)
        completed_fraction = completed_fraction - i_restart

      return i_restart, completed_fraction

    i_restart, completed_fraction = control_flow_ops.cond(
        math_ops.equal(t_mul, 1.0),
        lambda: compute_step(completed_fraction, geometric=False),
        lambda: compute_step(completed_fraction, geometric=True))

    m_fac = m_mul**i_restart
    cosine_decayed = 0.5 * m_fac * (
        1.0 + math_ops.cos(constant_op.constant(math.pi) * completed_fraction))
    decayed = (1 - alpha) * cosine_decayed + alpha

  return math_ops.multiply(learning_rate, decayed, name=name)


######layer normalization  method1
regularizer = tf.contrib.layers.l2_regularizer(scale = 3e-7)

def noam_norm(x, epsilon=1.0, scope=None, reuse=None):
    """One version of layer normalization."""
    with tf.name_scope(scope, default_name="noam_norm", values=[x]):
        shape = x.get_shape()
        ndims = len(shape)
        return tf.nn.l2_normalize(x, ndims - 1, epsilon=epsilon) * tf.sqrt(tf.to_float(shape[-1]))

def layer_norm_compute_python(x, epsilon, scale, bias):
    """Layer norm raw computation."""
    mean = tf.reduce_mean(x, axis=[-1], keep_dims=True)
    variance = tf.reduce_mean(tf.square(x - mean), axis=[-1], keep_dims=True)
    norm_x = (x - mean) * tf.rsqrt(variance + epsilon)
    return norm_x * scale + bias

def layer_norm(x, filters=None, epsilon=1e-6, scope=None, reuse=None):
    """Layer normalize the tensor x, averaging over the last dimension."""
    if filters is None:
        filters = x.get_shape()[-1]
    with tf.variable_scope(scope, default_name="layer_norm", values=[x], reuse=reuse):
        scale = tf.get_variable(
            "layer_norm_scale", [filters], regularizer = regularizer, initializer=tf.ones_initializer())
        bias = tf.get_variable(
            "layer_norm_bias", [filters], regularizer = regularizer, initializer=tf.zeros_initializer())
        result = layer_norm_compute_python(x, epsilon, scale, bias)
        return result


#####method2
def layer_normalization(x, scope,reuse=None):
    """
    x should be:[batch_size,sequence_length,d_model]
    :return:
    """
    filter = x.get_shape()[-1]  # last dimension of x. e.g. 512
    with tf.variable_scope(scope,reuse=reuse):
        # 1. normalize input by using  mean and variance according to last dimension
        mean = tf.reduce_mean(x, axis=-1, keep_dims=True)  # [batch_size,sequence_length,1]
        variance = tf.reduce_mean(tf.square(x - mean), axis=-1, keep_dims=True)  # [batch_size,sequence_length,1]
        norm_x = (x - mean) * tf.rsqrt(variance + 1e-6)  # [batch_size,sequence_length,d_model]
        # 2. re-scale normalized input back
        scale = tf.get_variable("layer_norm_scale", [filter], initializer=tf.ones_initializer)  # [filter]
        bias = tf.get_variable("layer_norm_bias", [filter], initializer=tf.ones_initializer)  # [filter]
        output = norm_x * scale + bias  # [batch_size,sequence_length,d_model]
        return output  # [batch_size,sequence_length,d_model]
