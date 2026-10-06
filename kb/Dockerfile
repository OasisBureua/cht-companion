FROM public.ecr.aws/lambda/python:3.11

COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements.txt --target ${LAMBDA_TASK_ROOT}

COPY handler.py captions.py chunking.py discovery.py documents.py embedding.py enqueue.py ingest.py store.py transcripts.py youtube_auth.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.handler"]
