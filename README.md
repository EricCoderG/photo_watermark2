# Photo Watermark2 运行手册

仅包含在 **macOS** 上本地运行的最简步骤，提供 **pip3** 与 **conda** 两种方式。

## 使用 pip3
```bash
# 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip3 install -r requirements.txt

# 运行
python3 main.py
```


## 使用 conda
```bash
# 创建并激活环境（Python 3.10+）
conda create -n watermark python=3.10 -y
conda activate watermark

# 安装依赖（任选其一）
# A. conda 安装
conda install -c conda-forge pyside6 pillow -y
# B. pip 安装（在该 conda 环境内）
# pip3 install -r requirements.txt

# 运行
python main.py
```