FROM public.ecr.aws/lambda/python:3.11

# Set working directory (this is already set in base image)
ENV LAMBDA_TASK_ROOT=/var/task
WORKDIR ${LAMBDA_TASK_ROOT}

RUN yum install -y mesa-libGL

# Copy files directly to /var/task (the Lambda default code root)
COPY backend/app/ .
COPY logic ./logic

RUN pip install --upgrade pip setuptools wheel --no-cache-dir && \
    pip install --only-binary=:all: --no-cache-dir -r requirements.txt && \
    pip install --only-binary=:all: --no-cache-dir -r logic/requirements.txt && \
    rm -rf /root/.cache/pip && \
    find . -type d -name '__pycache__' -exec rm -rf {} +

RUN find . -type d \( -name 'tests' -o -name 'test' -o -name 'docs' \) -exec rm -rf {} +

RUN chmod 644 ${LAMBDA_TASK_ROOT}/*.py
RUN find ${LAMBDA_TASK_ROOT} -type f -name "*.py" -exec chmod 644 {} \;
RUN find ${LAMBDA_TASK_ROOT} -type d -exec chmod 755 {} \;

ENV deployment=aws
ENV s3_output_bucket=colorize-output-bucket

CMD ["lambda_handler.handler"]