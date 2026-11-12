FROM python:3.11-slim

WORKDIR /app
COPY app.py ./

# curl_cffi 会伪装成 Chrome 的 TLS 指纹，云主机上比 urllib 更容易过 Cloudflare
RUN pip install --no-cache-dir curl_cffi

ENV PORT=8000 \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "app.py"]
