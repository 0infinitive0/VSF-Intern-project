FROM apache/airflow:3.3.0

USER airflow
COPY requirements.txt /tmp/vsf-airflow-requirements.txt
RUN pip install --no-cache-dir -r /tmp/vsf-airflow-requirements.txt

USER root
RUN /home/airflow/.local/bin/playwright install-deps chromium

USER airflow
RUN playwright install chromium
