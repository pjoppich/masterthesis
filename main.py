# -*- coding: utf-8 -*-
'''

The following libraries are used:
[1] NIFTy â€“ Numerical Information Field Theory, https://gitlab.mpcdf.mpg.de/ift/nifty
[2] NumPy - Numerical Python, https://numpy.org/
[3] Tensorflow - Tensorflow, https://www.tensorflow.org/
[4] Keras - Keras, https://keras.io/
[5] Matplotlib - Matplotlib, https://matplotlib.org/
[6] SciPy - Scientific Python, https://www.scipy.org/
[7] random - random, https://docs.python.org/3/library/random.html
[8] sklearn - https://scikit-learn.org/

Within helper_functions.py, Conv.py and Mask.py, the following libraries are used (these may be obsolete and omittable for the core task):
[9] PIL - Pillow (only Image-function), https://pillow.readthedocs.io/en/stable/
[10] warnings - warnings, https://docs.python.org/3/library/warnings.html
[11] random - random, https://docs.python.org/3/library/random.html
[12] skimage - scikit-image (only resize-function), https://scikit-image.org

All Neural Networks were built with Keras and saved as tensorflow-objects. Neural Netowrks are optimized for MNIST, good performance is observed for
F-MNIST.
'''
# Commented out IPython magic to ensure Python compatibility.
# Colab and system related
import os
import sys
import nifty6 as ift

###
# Necessary to convert tensorflow-object (e.g. Neural Network) to Nifty-Operator
sys.path.append('corrupted_data_classification/helper_functions/')


from operators.tensorflow_operator import TensorFlowOperator
###
import tensorflow as tf
# Include path to access helper functions and Mask / Conv Operator
sys.path.append('corrupted_data_classification/helper_functions/')
from helper_functions import clear_axis, gaussian, get_cmap, info_text, get_noise, rotation, split_validation_set
import Mask # Masking Operator
import Conv # Convolution Operator
sys.path.remove
# Tensorflow

# Plotting
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.cm as cm 
import matplotlib.pyplot as plt
# %matplotlib inline
plt.rcParams['figure.dpi'] = 200 # 200 e.g. is really fine, but slower

# Numerics
import random
import numpy as np
from sklearn.neighbors import KernelDensity
from scipy.stats import multivariate_normal
import sklearn as sk
from sklearn import decomposition

# Choose dataset
dataset = 'mnist' #'mnist, 'fashion_mnist'
datasource = getattr(tf.keras.datasets, dataset)
(XTrain, YTrain), (XTest, YTest) = datasource.load_data()
XTrain, XTest = XTrain / 255.0, XTest / 255.0

x_shape = XTrain[1].shape[0]
y_shape = XTrain[1].shape[1]
try:
  z_shape = XTrain[1].shape[2]
  img_shape = [x_shape, y_shape, z_shape]
except:
  img_shape = [x_shape, y_shape]

xy_shape = x_shape * y_shape
flattened_shape = np.prod(img_shape)
# Reshape Xtrain and XTest to flattened Vectors instead of square arrays
if dataset == 'mnist' or dataset== 'fashion_mnist':
  XTrain = XTrain.reshape((len(XTrain), np.prod(XTrain.shape[1:])))
  XTest = XTest.reshape((len(XTest), np.prod(XTest.shape[1:])))

n_classes = len(np.unique(YTrain))

# Session for tensorflow v1 compatibility
sess = tf.compat.v1.InteractiveSession()
graph = tf.compat.v1.get_default_graph()

###
# [4]
###
# Split Training-Dataset into additional validation set.
XTrain, YTrain, XVal, YVal = split_validation_set(XTrain, YTrain, val_perc=0.2)
# Read in model#

if dataset=='mnist': 
  Decoder_tf = tf.keras.models.load_model('./corrupted_data_classification/NNs/MNIST/pretrained_supervised_ae10/Decoder', compile=False)
  Encoder_tf = tf.keras.models.load_model('./corrupted_data_classification/NNs/MNIST/pretrained_supervised_ae10/Encoder', compile=False)
  
if dataset=='fashion_mnist': 
  Decoder_tf = tf.keras.models.load_model('./corrupted_data_classification/NNs/Fashion-MNIST/pretrained_supervised_ae10/Decoder', compile=False)
  Encoder_tf = tf.keras.models.load_model('./corrupted_data_classification/NNs/Fashion-MNIST/pretrained_supervised_ae10/Encoder', compile=False)

# Define ift-space
# position_space: Also data-space. Equal to the vectorized image dimension. For MNIST-Images, the position-space's
# dimensions are 784x1
position_space = ift.UnstructuredDomain(Decoder_tf.get_layer(index=-1).output_shape[1:])

# n_latent: number of latent space activations
n_latent = Encoder_tf.get_layer(index=-1).output_shape[-1]
# latent_space: Domain with dimensions of the latent space
latent_space = ift.UnstructuredDomain([n_latent])

# Initialize Parameters
# Pre-Defined parameters by Max-Planck-Institute
comm, _, _, master = ift.utilities.get_MPI_params()

# Convert Encoder and Decoder to nifty-operators (``TensorFlowOperator``)
Decoder = TensorFlowOperator(Decoder_tf.layers[-1].output, Decoder_tf.layers[0].output, latent_space, position_space)
Encoder = TensorFlowOperator(Encoder_tf.layers[-1].output, Encoder_tf.layers[0].output, position_space, latent_space)

# Choose how to classify data, once it has been reconstructed (any classifier of MNIST data my be chosen here).
Classifier = Encoder
#Classifier = TensorFlowOperator(Classifier_tf.layers[-2].output, Classifier_tf.layers[0].output, position_space,ift.UnstructuredDomain(n_classes))

# Get all activations in the latent space from Encoder with Validation Dataset -> latent_values
latent_values = np.zeros((len(XVal), n_latent))
for i, pic in enumerate(XVal):
  pic = np.reshape(pic, position_space.shape)
  latent_values[i, :] = Encoder(ift.Field.from_raw(position_space, pic)).val  

# Fill means-array with mean activation of every picture
means = np.zeros([n_latent, n_classes])
for pic in range(n_classes):
  for weight in range(n_latent):
    means[weight, pic] = np.mean(latent_values[np.where(YVal == pic), weight])

# Define overall mean of all activations in latent-space
mean = ift.Field.from_raw(latent_space, np.mean(latent_values, axis=0)) #mean of all activations in latent
Mean = ift.Adder(mean)

# Fill cov_all_variables with covariances of activation of every digit;
# Get cov_supervised_variables with covariances of only supervised activations
cov_all_variables = [[np.zeros([n_latent, n_latent])] for y in range(n_classes)]
cov_supervised_variables = [[np.zeros([n_classes, n_classes])] for y in range(n_classes)]

for i in range(n_classes):
  cov_all_variables[i] = np.cov(latent_values[np.where(YVal==i)[0]][:,:], rowvar=False)
  cov_supervised_variables[i] = np.cov(latent_values[np.where(YVal==i)[0]][:,:10], rowvar=False)

# Fill overall covariance of all activations in latent space
cov = np.zeros([n_latent, n_latent])
cov = np.cov(latent_values, rowvar=False)

# Transform covariance matrix into standardized space by Cholesky factorization
# cov = AA^T
A = ift.MatrixProductOperator(ift.UnstructuredDomain([n_latent]), np.linalg.cholesky(cov))

''' 
Generate Ground Truth either 
    --> from Sampling from latent distribution OR
    --> from drawing a sample from independent partition of dataset
'''
## Sampling from latent distribution
#xi = ift.from_random(latent_space, 'normal')
#s = A.apply(xi, 1) + mean
#ground_truth = Decoder(s)

## Drawing sample from dataset
p=3
#p = 10
ground_truth = ift.Field.from_raw(position_space, np.reshape(XTest[p], position_space.shape))

'''
Data Corruption:

1. Mask --> Operator: M (no_mask, half_mask, corner_mask, checkerboard_mask, random_mask)
2. Noise --> Operator: N 
3. Convolution --> Operator: C (sobel, gaussian_blur, edge_detection, own)

Data Modification (not included in modeling-process; thus the Model "does not 
know" these modifications):

4. Rotation (angle)

X. Response --> Operator: R (Concatenated Mask, Noise and Convolution)
'''
p = 10 # Specify element of XTest that is to be corrupted and to be evaluated; can be arbitrary integer within length of XTest

ground_truth = ift.Field.from_raw(position_space, np.reshape(XTest[p], position_space.shape))
# 1. Mask
M = Mask.no_mask(position_space=position_space)
#M = Mask.half_mask(position_space=position_space, mask_range=0.5)
#M = Mask.random_mask(position_space=position_space, seed=10, n_blobs=25)

# 2. Noise
N, n = get_noise(noise_level=1, position_space=position_space, seed=10)

# 3. Convolution
#C = Conv.gaussian_blur(7, 1, position_space=position_space) # sobel, edge_detection, 

# 4. Rotation (not included in data-model, reconstruction may be poor!)
# Specify angle in degrees (clockwise rotation)
ground_truth_rot = rotation(ground_truth, img_shape, angle=0)

# Apply Data Corruption to Ground Truth and creeate Response operator

GR = ift.GeometryRemover(position_space)
R = GR(M) # Without Convolution
#R = GR(M @ C) # With Convolution
data = R((ground_truth_rot))+n # Apply Response R on (rotated) ground truth --> Noise is applicated after masking
plt.imshow(np.reshape(data.val, [28,28]))

# Define Hyperparameters for minimizer via Iteration-Controllers
# These Hyperparameters are not fully optimized!

ic_sampling = ift.AbsDeltaEnergyController(name='Sampling', deltaE=1e-2, iteration_limit=150)
ic_newton = ift.AbsDeltaEnergyController(name='Newton', deltaE=5e-2, iteration_limit=150)
minimizer = ift.NewtonCG(ic_newton)

'''
Define Likelihood as Gaussian Energy
mean: data (corruped image with R applied)
inverse_covariance: Inverse of Noise-Matrix N
R: Response Operator
Decoder: Generator mapping data from latent space to image space
Mean: Adder Operator; Mean of all latent Space activations
A: Product Operator; Transformed Covariance of all latent space activations

Mean and A originate from the following transformation: 
s = A*xi+Mean

'''
likelihood = ift.GaussianEnergy(mean=data, inverse_covariance=N.inverse) @ R @ Decoder @ Mean @ A
H = ift.StandardHamiltonian(likelihood, ic_sampling)

# Run MGVI (Metric Gaussian Variational Inference)
n_samples = 50 # Define number of samples with which posterior distribution is approximated; more samples => higher runtime, higher accuracy

def MGVI(n_samples, H):
    initial_mean = ift.Field.full(latent_space, 0.) # Define initial activation; random initialization works as well
    mu = initial_mean
    for i in range(5): 
      # Draw new samples and minimize KL
      KL = ift.MetricGaussianKL(mu, H, n_samples, mirror_samples=False) # Set up KL with current mu
      KL, convergence = minimizer(KL) # Minimize KL and check for convergence
      mu = KL.position # Set minimized KL as new mu
    KL = ift.MetricGaussianKL(mu, H, n_samples, mirror_samples=False)
    KL, convergence = minimizer(KL)
    return KL

iters=1 # Define number of iterations of posterior approximation. This might be helpful to check "how certain" the approximation is and if only an unstable local minimum is found
KL_iterations = []
for i in range(iters):
  KL_iterations.append(MGVI(n_samples, H))

# Draw inferred signal from posterior samples and transform to original space
sc = ift.StatCalculator()

for i in range(iters):
  KL = KL_iterations[i]
  for sample in KL.samples:
    sc.add(A.apply(sample + KL.position, 1) + mean) # Retransform signal s = A*xi+mu

posterior_mean = sc.mean # Get mean of all samples
posterior_std = ift.sqrt(sc.var) # Get standard deviation of all samples

# Classify posteriors via mahalanobis-distance and by classifying all posterior samples
# with seperatly trained network ('Classifier')
mahalanobis_distance_supervised = np.zeros([iters*n_samples, n_classes])
mahalanobis_distance = np.zeros([iters*n_samples, n_classes])
classified_posteriors = np.zeros([iters*n_samples, n_latent])
latent_posteriors = np.zeros([iters*n_samples, n_latent])

for k in range(iters):
  KL = KL_iterations[k]
  for j, sample in enumerate(KL.samples):
    s_posterior = A.apply(sample + KL.position, 1) + mean

    latent_posteriors[j+k*n_samples, :] = s_posterior.val
    classified_posteriors[j+k*n_samples, :] = Classifier(Decoder(s_posterior)).val
    for i in range(n_classes):
      mahalanobis_distance_supervised[j+k*n_samples, i] = np.sqrt((s_posterior.val[:n_classes] - means[:n_classes,i]).T @ np.linalg.inv(cov_supervised_variables[i]) @ (s_posterior.val[:n_classes] - means[:n_classes,i]))
      mahalanobis_distance[j+k*n_samples, i] = np.sqrt((s_posterior.val - means[:,i]).T @ np.linalg.inv(cov_all_variables[i]) @ (s_posterior.val - means[:,i]))
      #mahalanobis_distance[j+k*n_samples, i] = np.sqrt((s_posterior.val - means[:,i]).T @  (s_posterior.val - means[:,i])) # Euclidian Distance


mahalanobis_mean = np.mean(mahalanobis_distance, axis=0)
mahalanobis_std = np.sqrt(np.var(mahalanobis_distance, axis=0))

mahalanobis_mean_supervised = np.mean(mahalanobis_distance_supervised, axis=0)
mahalanobis_std_supervised = np.sqrt(np.var(mahalanobis_distance_supervised, axis=0))

classified_mean = np.mean(classified_posteriors, axis=0)
classified_std = np.std(classified_posteriors, axis=0)

# Get all classifications of posterior samples for pie-plot visualization

classified_posteriors_nn = np.sort(np.argmax(classified_posteriors, axis=1))
classified_posteriors_dm = np.sort(np.argmin(mahalanobis_distance, axis=1))
for i in range(n_classes):
  unique_digit_nn, count_nn = np.unique(classified_posteriors_nn, return_counts=True)
  unique_digit_dm, count_dm = np.unique(classified_posteriors_dm, return_counts=True)
counts_nn = dict(zip(unique_digit_nn, count_nn))
counts_dm = dict(zip(unique_digit_dm, count_dm))

viridis = cm.get_cmap('viridis', n_classes)
pie_colors = viridis(np.linspace(0, 1, n_classes))

# Create dictionary with important information:
# Top scores of respective classification method (M-Dist, NN)
# True or false classification (only valid if Labels given)
# Overlapping standard-deviations

n_scores = 3 # Number of top scoring elements to be displayed (max: n_classes)
top_scores_nn = list(reversed(np.argsort(classified_mean)[-n_scores:]))
top_scores_dm = list(np.argsort(mahalanobis_mean)[:n_scores])

overlap_bottom_nn = np.zeros(n_scores-1)
overlap_bottom_dm = np.zeros(n_scores-1)

for i in range(n_scores-1):
  overlap_bottom_nn[i] = (classified_mean[top_scores_nn[0]] - classified_std[top_scores_nn[0]]) - (classified_mean[top_scores_nn[i+1]] + classified_std[top_scores_nn[i+1]])
  overlap_bottom_dm[i] = (mahalanobis_mean[top_scores_dm[i+1]] - mahalanobis_std[top_scores_dm[i+1]]) - (mahalanobis_mean[top_scores_dm[0]] + mahalanobis_std[top_scores_dm[0]])


keys_nn = ['Measure','Top Scores:', 'Classification:', 'ID:', 'N Samples:']
keys_dm = ['Measure','Top Scores:', 'Classification:', 'ID:', 'N Samples:', 'M-Dist of {}:'.format(top_scores_dm[0])]


if top_scores_nn[0] == YTrain[-p]:
  values_nn = ['Neural Net Classifier','{}'.format(tuple(top_scores_nn)), 'True', 'YTrain[-{}]'.format(p), '{}'.format(n_samples)]

if top_scores_dm[0] == YTrain[-p]:
  values_dm = ['Mahalanobis Distance','{}'.format(tuple(top_scores_dm)), 'True', 'YTrain[-{}]'.format(p), '{}'.format(n_samples), '{}'.format(mahalanobis_mean[top_scores_dm[0]])]

if top_scores_nn[0] != YTrain[-p]:
  values_nn = ['Neural Net Classifier','{}'.format(tuple(top_scores_nn)), 'False', 'YTrain[-{}]'.format(p), '{}'.format(n_samples)]
if top_scores_dm[0] != YTrain[-p]:
  values_dm = ['Mahalanobis Distance','{}'.format(tuple(top_scores_dm)), 'False', 'YTrain[-{}]'.format(p), '{}'.format(n_samples), '{}'.format(mahalanobis_mean[top_scores_dm[0]])]


# Store Overlapping in Dictionary, expressed in terms of sigmas/STD of top Scoring digit

for i in range(n_scores - 1):
  keys_nn.append('Overlap [sigmas] {} --> {}'.format(top_scores_nn[0], top_scores_nn[i+1]))
  values_nn.append(overlap_bottom_nn[i] / classified_std[top_scores_nn[0]])
  keys_dm.append('Overlap [sigmas] {} --> {}'.format(top_scores_dm[0], top_scores_dm[i+1]))
  values_dm.append(overlap_bottom_dm[i] / mahalanobis_std[top_scores_dm[0]])

overlapping_nn = dict(zip(keys_nn, values_nn))
overlapping_dm = dict(zip(keys_dm, values_dm))


min = np.min([posterior_mean.val])
max = np.max([posterior_mean.val])

plt.subplot(3, 4, 1)
barplot = plt.bar(range(n_classes), posterior_mean.val[0:n_classes], alpha=1, width=0.8, yerr=posterior_std.val[0:n_classes], label='MGVI with STD')
barplot[np.where(posterior_mean.val == np.max(posterior_mean.val[:10]))[0][0]].set_color('r')
plt.legend(fontsize=3)
plt.title('$h\pm\delta_r$', fontsize=8)
plt.xticks(range(n_classes), fontsize=6)
plt.yticks(fontsize=6)

plt.subplot(3, 4, 2)
barplot = plt.bar(range(n_classes), classified_mean[:10], yerr=classified_std[:10])
plt.xticks(np.arange(n_classes), fontsize=6)
plt.yticks(fontsize=6)

barplot[np.where(classified_mean == np.max(classified_mean))[0][0]].set_color('r')
plt.title('$f(g(h))\pm \delta_r$', fontsize=8)

plt.subplot(3, 4, 3)
m_mean = mahalanobis_mean_supervised
m_std = mahalanobis_std_supervised
barplot = plt.bar(range(n_classes), m_mean, yerr=m_std)
barplot[np.where(m_mean == np.min(m_mean))[0][0]].set_color('r')
for bar in barplot:
   yval = bar.get_height()
   yval = np.round(yval, decimals=2)
   plt.annotate('{}'.format(yval),
                    xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    xytext=(0, 3),  # 3 points vertical offset
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=5, rotation=45)
plt.title('$\delta_m\pm \delta_r$', fontsize=8)
plt.ylim(0, 1.3*np.max(m_mean))
plt.xticks(np.arange(n_classes), fontsize=6)
plt.yticks(fontsize=6)

plt.subplot(3, 4, 5)
plt.imshow(np.reshape(data.val, img_shape))
plt.xlabel('Mock Signal')
clear_axis()
plt.xticks(fontsize=6)
plt.yticks(fontsize=6)

plt.subplot(3, 4, 6)
plt.imshow(np.reshape(ground_truth.val, img_shape))
plt.xlabel('Ground Truth: {}'.format(YTest[p]), fontsize=8)
clear_axis()

plt.subplot(3, 4, 7)
plt.imshow(np.reshape(Decoder(posterior_mean).val, img_shape))
plt.xlabel('Reconstruction', fontsize=8)
clear_axis()

plt.subplot(3, 4, 4)
plt.pie([float(v) for v in counts_nn.values()], labels=[float(k) for k in counts_nn.keys()],autopct='%1.1f%%', colors=pie_colors[list(counts_nn.keys())], textprops={'fontsize': 4} )
plt.xlabel('Class. Post. NN', fontsize=8)
plt.subplot(3, 4, 8)
plt.pie([float(v) for v in counts_dm.values()], labels=[float(k) for k in counts_dm.keys()],autopct='%1.1f%%', colors=pie_colors[list(counts_dm.keys())], textprops={'fontsize': 4})
plt.xlabel('Class. Post. $d_M$', fontsize=8)

plt.savefig('./corrupted_data_classification/{}'.format('example_results'))

# Visualize reconstructions of all posterior samples. Output dependent on n_samples.

grid = plt.GridSpec(np.int(np.floor(np.sqrt(len(latent_posteriors)))), np.int(np.ceil(np.sqrt(len(latent_posteriors)))), wspace=0.1, hspace=0.1)
k=0
latent_posteriors=latent_posteriors[latent_posteriors[:,5].argsort()]
for i in range(np.int(np.floor(np.sqrt(len(latent_posteriors))))):
  for j in range(np.int(np.ceil(np.sqrt(len(latent_posteriors))))):
    if k < iters*n_samples:
      plt.subplot(grid[i, j])
      plt.imshow(np.reshape(Decoder(ift.Field.from_raw(latent_space, latent_posteriors[k, :])).val, img_shape), 'gray')
      clear_axis()
      k += 1
    else:
      break
fig = plt.gcf()
plt.savefig('./corrupted_data_classification/{}'.format('example_samples'))
print('Done. Results saved.')
