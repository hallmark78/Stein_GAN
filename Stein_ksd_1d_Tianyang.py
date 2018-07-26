import tensorflow as tf
from tensorflow.python import debug as tf_debug
import numpy as np
import matplotlib.pyplot as plt
import os

DIR = os.getcwd() + "/output/"
EXP = "072618-1"
EXP_DIR = DIR + EXP + "/"
if not os.path.exists(EXP_DIR):
    os.makedirs(EXP_DIR)

mb_size = 100
X_dim = 1  # dimension of the target distribution, 3 for e.g.
z_dim = 1
h_dim_g = 50
h_dim_d = 50
N, n_D, n_G = 200, 1, 1  # num of iterations


mu1 = 1
Sigma1 = 1
Sigma1_inv = 1/Sigma1

################################################################################################
################################################################################################

info = open(EXP_DIR + "info.txt", 'w')
info.write("Description: " +
           '\n\n' + ("=" * 80 + '\n') * 3 + '\n' +
           "Model Parameters: \n\t" +
           "\n\t".join(['mu1 = {}'.format(mu1), 'sigma1 = {}'.format(Sigma1)]) +
           '\n\n' + ("=" * 80 + '\n') * 3 + '\n' +
           "Network Parameters: \n\t" +
           "\n\t".join(['mb_size = {}'.format(mb_size), 'X_dim = {}'.format(X_dim), 'z_dim = {}'.format(z_dim),
                        'h_dim_g = {}'.format(h_dim_g), 'h_dim_d = {}'.format(h_dim_d), 'n_D = {}'.format(n_D),
                        'n_G = {}'.format(n_G)]) +
           '\n\n' + ("=" * 80 + '\n') * 3 + '\n' +
           "Training iter: \n\t" +
           "\n\t".join(['n_D = {}'.format(n_D), 'n_G = {}'.format(n_G)]) +
           '\n\n' + ("=" * 80 + '\n') * 3 + '\n'
           "Additional Information: \n" +
           "" + "\n")
info.close()


################################################################################################
################################################################################################
# convert parameters to tf tensor
mu1_tf = tf.reshape(tf.convert_to_tensor(mu1, dtype=tf.float32), shape=[1])

Sigma1_inv_tf = tf.reshape(tf.convert_to_tensor(Sigma1_inv, dtype=tf.float32), shape=[1, 1])

X = tf.placeholder(tf.float32, shape=[None, X_dim])

initializer = tf.contrib.layers.xavier_initializer()

D_W1 = tf.get_variable('D_w1', [X_dim, h_dim_d], dtype=tf.float32, initializer=initializer)
D_b1 = tf.get_variable('D_b1', [h_dim_d], initializer=initializer)
D_W2 = tf.get_variable('D_w2', [h_dim_d, X_dim], dtype=tf.float32, initializer=initializer)
D_b2 = tf.get_variable('D_b2', [X_dim], initializer=initializer)

theta_D = [D_W1, D_W2, D_b1, D_b2]


z = tf.placeholder(tf.float32, shape=[None, z_dim])

G_W1 = tf.get_variable('g_w1', [z_dim, X_dim], dtype=tf.float32, initializer=initializer)
G_b1 = tf.get_variable('g_b1', [X_dim], initializer=initializer)

theta_G = [G_W1, G_b1]


def log_densities(xs):
    log_den1 = - tf.diag_part(tf.matmul(tf.matmul(xs - mu1_tf, Sigma1_inv_tf),
                                        tf.transpose(xs - mu1_tf))) / 2
    return log_den1


def S_q(xs):
    return tf.matmul(mu1_tf - xs, Sigma1_inv_tf)
    # return tf.gradients(log_densities(xs), xs)[0]


def sample_z(m, n):
    return np.random.normal(0, 1, size=[m, n])


def generator(z):
    G_h1 = (tf.matmul(z, G_W1) + G_b1)
    return G_h1


def svgd_kernel(x, h=1.):  # adopted from reference
    XY = tf.matmul(x, tf.transpose(x))
    X2_ = tf.reduce_sum(tf.square(x), axis=1)
    x2 = tf.reshape(X2_, shape=[tf.shape(x)[0], 1])
    X2e = tf.tile(x2, [1, tf.shape(x)[0]])
    H = tf.subtract(tf.add(X2e, tf.transpose(X2e)), 2 * XY)

    Kxy = tf.exp(-H / h ** 2 / 2.0)
    expo = (h ** 2 - H) / h ** 4

    dxkxy = -tf.matmul(Kxy, x)
    sumkxy = tf.expand_dims(tf.reduce_sum(Kxy, axis=1), 1)
    dxkxy = tf.add(dxkxy, tf.multiply(x, sumkxy)) / (h ** 2)

    return Kxy, dxkxy, expo


# dimension n*n
def ksd_u(x):
    n = tf.shape(x)[0]
    s_q = S_q(x)
    K, dK, expo = svgd_kernel(x)
    t1 = tf.multiply(tf.matmul(s_q, tf.transpose(s_q)), K)
    # t2 = tf.matmul(s_q, tf.transpose(dK))
    xx = tf.tile(tf.expand_dims(x, 2), [1, 1, n])
    kk = tf.expand_dims(K, 1)
    kk = tf.tile(kk, [1, X_dim, 1])
    dx = xx - tf.transpose(xx, perm=[2, 1, 0])
    kdx = tf.multiply(dx, kk)
    t2 = tf.tensordot(s_q, -kdx, axes=[[1], [1]])
    t2 = tf.stack([t2[i][i] for i in range(mb_size)], axis=0)
    t3 = tf.multiply(K, expo)

    # p1 is S_q*K(x, )  the dimension is n*d
    sq = tf.expand_dims(s_q, 2)
    sq = tf.tile(sq, [1, 1, n])
    p1 = tf.reduce_sum(tf.multiply(sq, kk), axis=0)
    p1 = tf.reshape(p1, shape=[X_dim, n])
    return t1 + t2 - tf.transpose(t2) + t3, (tf.transpose(p1) + dK)/tf.cast(n, dtype=tf.float32)


# sess = tf.Session()
# sess.run((ksd_u(z)), feed_dict={z: sample_z(10, 1)})


# sum over off diagonal elements
def ksd_emp(x):
    U, phi = ksd_u(x)
    _ksd = (tf.reduce_sum(U) - tf.reduce_sum(tf.diag_part(U)))/mb_size/(mb_size-1)
    return _ksd, phi/_ksd**2


def diag_gradient(y, x):
    dg = tf.stack([tf.gradients(y[:, i], x)[0][:, i] for i in range(X_dim)], axis=0)
    return tf.transpose(dg)


G_sample = generator(z)

ksd, D_fake = ksd_emp(G_sample)

range_penalty_g = 10*(generator(tf.constant(1, shape=[1, 1], dtype=tf.float32)) -
                      generator(tf.constant(-1, shape=[1, 1], dtype=tf.float32)))
# range_penalty_g = tf.Print(range_penalty_g, [range_penalty_g], message="range_penalty_g"+"-values:")

Loss = (tf.reduce_mean(tf.reduce_sum(tf.multiply(S_q(G_sample), D_fake), 1) + tf.gradients(D_fake, G_sample)[0]))

G_solver = (tf.train.GradientDescentOptimizer(learning_rate=1e-1).minimize(Loss, var_list=theta_G))

G_solver_ksd = (tf.train.GradientDescentOptimizer(learning_rate=1e-1).minimize(ksd, var_list=theta_G))


#######################################################################################################################
sess = tf.Session()
sess.run(tf.global_variables_initializer())


ksd_loss = np.zeros(N)
G_loss = np.zeros(N)
D_Loss_curr = G_Loss_curr = None

for it in range(N):
    for _ in range(n_G):
        _, G_Loss_curr, ksd_curr = sess.run([G_solver_ksd, Loss, ksd],
                                            feed_dict={z: sample_z(mb_size, z_dim)})
    G_loss[it] = G_Loss_curr
    ksd_loss[it] = ksd_curr

    if np.isnan(G_Loss_curr):
        print("G_loss:", it)
        break

    if it % 10 == 0:
        noise = sample_z(100, 1)
        x_range = np.reshape(np.linspace(-5, 5, 500, dtype=np.float32), newshape=[500, 1])
        z_range = np.reshape(np.linspace(-5, 5, 500, dtype=np.float32), newshape=[500, 1])
        samples = sess.run(generator(noise.astype(np.float32)))
        gen_func = sess.run(generator(z_range))
        sample_mean = np.mean(samples)
        sample_sd = np.std(samples)
        print(it, ":", sample_mean, sample_sd)
        print("ksd_loss:", ksd_curr)
        print("G_loss:", G_Loss_curr)
        print("w:", G_W1.eval(session=sess), "b:", G_b1.eval(session=sess))
        # plt.scatter(samples[:, 0], samples[:, 1], color='b')
        # plt.scatter([mu1[0], mu2[0]], [mu1[1], mu2[1]], color="r")
        plt.plot()
        # plt.subplot(212)
        # plt.plot(x_range, disc_func)
        plt.subplot(212)
        plt.ylim(-5, 5)
        plt.plot(z_range, gen_func)
        plt.subplot(211)
        plt.ylim(-3, 5)
        plt.plot(range(100), samples[:, 0], 'ro', color='b', ms=1)
        plt.axhline(mu1, color='r')
        plt.title(
            "iter {0:04d}, {{G: {1:.4f}, mu: {2:.4f}, sd: {3:.4f}}}".format(it, G_Loss_curr, sample_mean, sample_sd))
        plt.savefig(EXP_DIR + "iter {0:04d}".format(it))
        plt.close()

sess.close()


np.savetxt(EXP_DIR + "loss_ksd.csv", ksd_loss, delimiter=",")
plt.plot(ksd_loss)
plt.ylim(ymin=0)
plt.axvline(np.argmin(ksd_loss), ymax=np.min(ksd_loss), color="r")
plt.title("KSD (min at iter {})".format(np.argmin(ksd_loss)))
plt.savefig(EXP_DIR + "ksd.png", format="png")
plt.close()

