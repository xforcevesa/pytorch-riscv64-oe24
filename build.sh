source ~/venv/bin/activate

export _GLIBCXX_USE_CXX11_ABI=1
export USE_CUDA=0
export USE_DISTRIBUTED=0
export USE_MKLDNN=0
export MAX_JOBS=5

python setup.py bdist_wheel --cmake
