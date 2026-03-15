FROM python:3.11-slim

WORKDIR /app

# 先复制依赖文件，利用 Docker layer 缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY . .

# 创建临时目录（tokens/ 和 downloads/ 会通过 volume 挂载）
RUN mkdir -p downloads tokens

CMD ["python", "main.py"]
