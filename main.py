# -*- coding: utf-8 -*-


"""
DEEP LEARNING FOR HYPERSPECTRAL DATA.

This script allows the user to run several deep models (and SVM baselines)
against various hyperspectral datasets. It is designed to quickly benchmark
state-of-the-art CNNs on various public hyperspectral datasets.

This code is released under the GPLv3 license for non-commercial and research
purposes only.
For commercial use, please contact the authors.
"""

# Python 2/3 compatiblity
from __future__ import print_function
from __future__ import division


# 自加，增加修改路径
import sys,os
curPath = os.path.abspath(os.path.dirname(__file__))
rootPath = os.path.split(curPath)[0]
sys.path.append(rootPath)
sys.path.append('E:\\Anaconda\\lib\\site-packages\\')
print('Path initialization finished\n')

# Torch
import torch
import torch.utils.data as data
from torchsummary import summary

# Numpy, scipy, scikit-image, spectral
import numpy as np
import sklearn.svm
import sklearn.model_selection
from skimage import io

# Visualization
import seaborn as sns
import visdom

import os

# import 自定义模块
from utils import metrics, convert_to_color_, convert_from_color_,\
    display_dataset, display_predictions, explore_spectrums, plot_spectrums,\
    sample_gt, build_dataset, show_results, compute_imf_weights, get_device, samples_per_class
from utils import show_Hyperparameter
from datasets import get_dataset, HyperX, open_file, DATASETS_CONFIG
from models import get_model, train, test, save_model

# 命令行解析器
import argparse

# -------------自加解决RuntimeError: cuDNN error: CUDNN_STATUS_BAD_PARAM---------------
torch.backends.cudnn.enabled = False
# -------------自加解决RuntimeError: cuDNN error: CUDNN_STATUS_BAD_PARAM---------------

# 获取DATASETS_CONFIG中的dataset_names，操作的对字典的操作。
dataset_names = [v['name'] if 'name' in v.keys() else k for k, v in DATASETS_CONFIG.items()]
# ['PaviaC', 'PaviaU', 'KSC', 'IndianPines', 'Botswana', 'DFC2018_HSI', 'OwnData']

# Argument parser for CLI interaction       # 用于CLI交互的参数解析器
parser = argparse.ArgumentParser(description="Run deep learning experiments on"
                                             " various hyperspectral datasets")

parser.add_argument('--dataset', type=str, default=None, choices=dataset_names,
                    help="Dataset to use.")
parser.add_argument('--model', type=str, default=None,
                    help="Model to train. Available:\n"
                    "SVM (linear),\n "
                    "SVM_grid (grid search on linear, poly and RBF kernels), \n"
                    "baseline (fully connected NN), \n"
                    "hu (1D CNN), \n"
                    "hamida (3D CNN + 1D classifier), \n"
                    "lee (3D FCN), \n"
                    "chen (3D CNN), \n"
                    "li (3D CNN), \n"
                    "he (3D CNN), \n"
                    "luo (3D CNN), \n"
                    "sharma (2D CNN), \n"
                    "boulch (1D semi-supervised CNN), \n"
                    "liu (3D semi-supervised CNN), \n"
                    "mou (1D RNN)")
parser.add_argument('--folder', type=str, help="Folder where to store the "
                    "datasets (defaults to the current working directory).",
                    default="./Datasets/")
parser.add_argument('--cuda', type=int, default=-1,
                    help="Specify CUDA device (defaults to -1, which learns on CPU)")
parser.add_argument('--runs', type=int, default=1, help="Number of runs (default: 1)")
parser.add_argument('--restore', type=str, default=None,
                    help="Weights to use for initialization, e.g. a checkpoint")

# Dataset options
group_dataset = parser.add_argument_group('Dataset')
group_dataset.add_argument('--training_sample', type=float, default=0.1,
                    help="Percentage of samples to use for training (default: 10%)")
group_dataset.add_argument('--sampling_mode', type=str, help="Sampling mode"
                    " (random sampling or disjoint, default: random)",
                    default='random')
group_dataset.add_argument('--train_set', type=str, default=None,
                    help="Path to the train ground truth (optional, this "
                    "supersedes(取代版本) the --sampling_mode option)")
group_dataset.add_argument('--test_set', type=str, default=None,
                    help="Path to the test set (optional, by default "
                    "the test_set is the entire ground truth minus the training)")
# Training options
group_train = parser.add_argument_group('Training')
group_train.add_argument('--epoch', type=int, help="Training epochs (optional, if"
                    " absent will be set by the model)")
group_train.add_argument('--patch_size', type=int,
                    help="Size of the spatial neighbourhood 空间邻域的大小 (optional, if "
                    "absent will be set by the model)")
group_train.add_argument('--lr', type=float,
                    help="Learning rate, set by the model if not specified.")
group_train.add_argument('--class_balancing', action='store_true',
                    help="Inverse median frequency class balancing (default = False)")
group_train.add_argument('--batch_size', type=int,
                    help="Batch size (optional, if absent will be set by the model")
group_train.add_argument('--test_stride', type=int, default=1,
                     help="Sliding window step stride during inference (default = 1)")
# Data augmentation parameters
group_da = parser.add_argument_group('Data augmentation')
group_da.add_argument('--flip_augmentation', action='store_true',
                    help="Random flips (if patch_size > 1)")
group_da.add_argument('--radiation_augmentation', action='store_true',
                    help="Random radiation noise (illumination)")
group_da.add_argument('--mixture_augmentation', action='store_true',
                    help="Random mixes between spectra")

parser.add_argument('--with_exploration', action='store_true',
                    help="See data exploration visualization")
parser.add_argument('--download', type=str, default=None, nargs='+',
                    choices=dataset_names,
                    help="Download the specified datasets and quits.")


# 解析参数
args = parser.parse_args()

# 操作参数
CUDA_DEVICE = get_device(args.cuda)

# % of training samples
SAMPLE_PERCENTAGE = args.training_sample
# Data augmentation 数据增强
FLIP_AUGMENTATION = args.flip_augmentation
RADIATION_AUGMENTATION = args.radiation_augmentation
MIXTURE_AUGMENTATION = args.mixture_augmentation
# Dataset name
DATASET = args.dataset
# Model name
MODEL = args.model
# Number of runs (for cross-validation)
N_RUNS = args.runs
# Spatial context size (number of neighbours in each spatial direction)
# 空间上下文大小（每个空间方向上的邻居数）
PATCH_SIZE = args.patch_size
# Add some visualization of the spectra ?   添加一些光谱可视化?
DATAVIZ = args.with_exploration
# Target folder to store/download/load the datasets
FOLDER = args.folder
# Number of epochs to run
EPOCH = args.epoch
# Sampling mode, e.g random sampling
SAMPLING_MODE = args.sampling_mode
# Pre-computed weights to restore
CHECKPOINT = args.restore
# Learning rate for the SGD
LEARNING_RATE = args.lr
# Automated class balancing
CLASS_BALANCING = args.class_balancing
# Training ground truth file
TRAIN_GT = args.train_set
# Testing ground truth file
TEST_GT = args.test_set
# Sliding window step stride during inference.
TEST_STRIDE = args.test_stride

# 设定随机数种子
np.random.seed(42)
torch.manual_seed(42)
torch.cuda.manual_seed(42)

if args.download is not None and len(args.download) > 0:
    for dataset in args.download:
        get_dataset(dataset, target_folder=FOLDER)
    quit()

viz = visdom.Visdom(env=DATASET + ' ' + MODEL)  # 设置visdom环境
if not viz.check_connection:                    # 检测与visdom服务器的连接
    print("Visdom is not connected. Did you run 'python -m visdom.server' ?")

# vars() 函数返回对象object的属性和属性值的字典对象。
hyperparams = vars(args)    # 以字典类型返回解析参数值，存入hyperparams

# Load the dataset          # 加载数据集
img, gt, LABEL_VALUES, IGNORED_LABELS, RGB_BANDS, palette = get_dataset(DATASET, FOLDER)
# 读取数据集样本数
label_map = {'Undefined': 0, 'Asphalt': 1, 'Meadows': 2, 'Gravel': 3, 'Trees': 4, 'Painted metal sheets': 5,
             'Bare Soil': 6, 'Bitumen': 7, 'Self-Blocking Bricks': 8, 'Shadows': 9}
all_count = samples_per_class(gt.flatten(), label_map=label_map)

# os.system('pause')

# LABEL_VALUES:
# ['Undefined', 'Asphalt', 'Meadows', 'Gravel', 'Trees', 'Painted metal sheets', 'Bare Soil', 'Bitumen', 'Self-Blocking Bricks', 'Shadows']
"""
img: 3D hyperspectral image (WxHxB)
gt: 2D int array of labels
label_values: list of class names
ignored_labels: list of int classes to ignore
rgb_bands: int tuple that correspond to red, green and blue bands
"""

# Number of classes
N_CLASSES = len(LABEL_VALUES)
# print(LABEL_VALUES)
# # ['Undefined', 'Asphalt', 'Meadows', 'Gravel', 'Trees', 'Painted metal sheets', 'Bare Soil', 'Bitumen', 'Self-Blocking Bricks', 'Shadows']

# Number of bands (last dimension of the image tensor)
N_BANDS = img.shape[-1]

# Parameters for the SVM grid search    SVM参数设定
SVM_GRID_PARAMS = [{'kernel': ['rbf'], 'gamma': [1e-1, 1e-2, 1e-3],
                                       'C': [1, 10, 100, 1000]},
                   {'kernel': ['linear'], 'C': [0.1, 1, 10, 100, 1000]},
                   {'kernel': ['poly'], 'degree': [3], 'gamma': [1e-1, 1e-2, 1e-3]}]

if palette is None:     # 调色板
    # Generate color palette
    palette = {0: (0, 0, 0)}
    for k, color in enumerate(sns.color_palette("hls", len(LABEL_VALUES) - 1)):
        palette[k + 1] = tuple(np.asarray(255 * np.array(color), dtype='uint8'))
invert_palette = {v: k for k, v in palette.items()}

# 调色板
def convert_to_color(x):
    return convert_to_color_(x, palette=palette)
def convert_from_color(x):
    return convert_from_color_(x, palette=invert_palette)


# Instantiate the experiment based on predefined networks   根据预定义的网络实例化实验
hyperparams.update({'n_classes': N_CLASSES, 'n_bands': N_BANDS, 'ignored_labels': IGNORED_LABELS, 'device': CUDA_DEVICE})
hyperparams = dict((k, v) for k, v in hyperparams.items() if v is not None)     # 遍历hyperparams将键值对再变成字典类型

# Show the image and the ground truth
display_dataset(img, gt, RGB_BANDS, LABEL_VALUES, palette, viz)
color_gt = convert_to_color(gt)

if DATAVIZ:     # ???
    # Data exploration : compute and show the mean spectrums
    mean_spectrums = explore_spectrums(img, gt, LABEL_VALUES, viz,
                                       ignored_labels=IGNORED_LABELS)
    plot_spectrums(mean_spectrums, viz, title='Mean spectrum/class')

results = []

# run the experiment several times
for run in range(N_RUNS):
    # 根据命令行输入参数确定train_gt和test_gt
    if TRAIN_GT is not None and TEST_GT is not None:
        train_gt = open_file(TRAIN_GT)
        test_gt = open_file(TEST_GT)
    elif TRAIN_GT is not None:
        train_gt = open_file(TRAIN_GT)
        test_gt = np.copy(gt)
        w, h = test_gt.shape
        test_gt[(train_gt > 0)[:w,:h]] = 0
    elif TEST_GT is not None:
        test_gt = open_file(TEST_GT)
    else:
    # Sample random training spectra    随机训练光谱样本（有训练集，有测试集）
        train_gt, test_gt = sample_gt(gt, SAMPLE_PERCENTAGE, mode=SAMPLING_MODE)

    print("{} samples selected (over {})".format(np.count_nonzero(train_gt),
                                                 np.count_nonzero(gt)))
    print("Running an experiment with the {} model".format(MODEL),
          "run {}/{}".format(run + 1, N_RUNS))

    # 打印测试集样本分布
    train_count = samples_per_class(train_gt.flatten(), label_map=label_map)

    os.system('pause')

    display_predictions(convert_to_color(train_gt), viz, caption="Train ground truth")
    display_predictions(convert_to_color(test_gt), viz, caption="Test ground truth")

    if MODEL == 'SVM_grid':
        print("Running a grid search SVM")
        # Grid search SVM (linear and RBF)
        X_train, y_train = build_dataset(img, train_gt,
                                         ignored_labels=IGNORED_LABELS)
        class_weight = 'balanced' if CLASS_BALANCING else None
        clf = sklearn.svm.SVC(class_weight=class_weight)
        clf = sklearn.model_selection.GridSearchCV(clf, SVM_GRID_PARAMS, verbose=5, n_jobs=4)
        clf.fit(X_train, y_train)
        print("SVM best parameters : {}".format(clf.best_params_))
        prediction = clf.predict(img.reshape(-1, N_BANDS))
        save_model(clf, MODEL, DATASET)
        prediction = prediction.reshape(img.shape[:2])
    elif MODEL == 'SVM':
        X_train, y_train = build_dataset(img, train_gt,
                                         ignored_labels=IGNORED_LABELS)
        class_weight = 'balanced' if CLASS_BALANCING else None
        clf = sklearn.svm.SVC(class_weight=class_weight)
        clf.fit(X_train, y_train)
        save_model(clf, MODEL, DATASET)
        prediction = clf.predict(img.reshape(-1, N_BANDS))
        prediction = prediction.reshape(img.shape[:2])
    elif MODEL == 'SGD':
        X_train, y_train = build_dataset(img, train_gt,
                                         ignored_labels=IGNORED_LABELS)
        X_train, y_train = sklearn.utils.shuffle(X_train, y_train)
        scaler = sklearn.preprocessing.StandardScaler()
        X_train = scaler.fit_transform(X_train)
        class_weight = 'balanced' if CLASS_BALANCING else None
        clf = sklearn.linear_model.SGDClassifier(class_weight=class_weight, learning_rate='optimal', tol=1e-3, average=10)
        clf.fit(X_train, y_train)
        save_model(clf, MODEL, DATASET)
        prediction = clf.predict(scaler.transform(img.reshape(-1, N_BANDS)))
        prediction = prediction.reshape(img.shape[:2])
    elif MODEL == 'nearest':
        X_train, y_train = build_dataset(img, train_gt,
                                         ignored_labels=IGNORED_LABELS)
        X_train, y_train = sklearn.utils.shuffle(X_train, y_train)
        class_weight = 'balanced' if CLASS_BALANCING else None
        clf = sklearn.neighbors.KNeighborsClassifier(weights='distance')
        clf = sklearn.model_selection.GridSearchCV(clf, {'n_neighbors': [1, 3, 5, 10, 20]}, verbose=5, n_jobs=4)
        clf.fit(X_train, y_train)
        clf.fit(X_train, y_train)
        save_model(clf, MODEL, DATASET)
        prediction = clf.predict(img.reshape(-1, N_BANDS))
        prediction = prediction.reshape(img.shape[:2])
    else:
        # Neural network
        model, optimizer, loss, hyperparams = get_model(MODEL, **hyperparams)

        # 打印超参数
        show_Hyperparameter(hyperparams)

        if CLASS_BALANCING:
            weights = compute_imf_weights(train_gt, N_CLASSES, IGNORED_LABELS)
            hyperparams['weights'] = torch.from_numpy(weights)

        # Split train set in train/val
        # 自加 修改val set的划分方式，从test set划分
        # train_gt, val_gt = sample_gt(train_gt, 0.95, mode='random')
        test_gt, val_gt = sample_gt(test_gt, 0.95, mode='random')

        # Generate the dataset
        train_dataset = HyperX(img, train_gt, **hyperparams)

        train_loader = data.DataLoader(train_dataset,
                                       batch_size=hyperparams['batch_size'],
                                       # pin_memory=hyperparams['device'],
                                       shuffle=True)

        val_dataset = HyperX(img, val_gt, **hyperparams)
        val_loader = data.DataLoader(val_dataset,
                                     # pin_memory=hyperparams['device'],
                                     batch_size=hyperparams['batch_size'])

        print("Network :")
        with torch.no_grad():
            for input, _ in train_loader:
                break
            summary(model.to(hyperparams['device']), input.size()[1:])

        # ---------------中断程序------------------
        # print([DATASET + ' ' + MODEL])
        os.system('pause')
        # ---------------中断程序------------------

        if CHECKPOINT is not None:
            model.load_state_dict(torch.load(CHECKPOINT))

        # 训练模型！！！
        try:
            train(model, optimizer, loss, train_loader, hyperparams['epoch'],
                  scheduler=hyperparams['scheduler'], device=hyperparams['device'],
                  supervision=hyperparams['supervision'], val_loader=val_loader,
                  display=viz,
                  img=img, gt=gt, hyperparams=hyperparams, n_classes=N_CLASSES, viz=viz, LABEL_VALUES=LABEL_VALUES)     # for metric
        except KeyboardInterrupt:
            # Allow the user to stop the training to do inference
            pass

        # 对整个数据集计算了预测，而不仅仅是对test做预测
        probabilities = test(model, img, hyperparams)
        prediction = np.argmax(probabilities, axis=-1)


    # run_results = metrics(prediction, test_gt, ignored_labels=hyperparams['ignored_labels'], n_classes=N_CLASSES)
    run_results = metrics(prediction, gt, ignored_labels=hyperparams['ignored_labels'], n_classes=N_CLASSES)

    mask = np.zeros(gt.shape, dtype='bool')
    for l in IGNORED_LABELS:
        mask[gt == l] = True
    prediction[mask] = 0

    color_prediction = convert_to_color(prediction)
    display_predictions(color_prediction, viz, gt=convert_to_color(gt), caption="Prediction vs. test ground truth")

    results.append(run_results)
    show_results(run_results, viz, label_values=LABEL_VALUES)

if N_RUNS > 1:
    show_results(results, viz, label_values=LABEL_VALUES, agregated=True)

# viz.save([DATASET + ' ' + MODEL])