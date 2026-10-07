# Embed worker: SQS messages and the S3 drop zone, Titan embeddings.
#   docker build -f Dockerfile -t kb-embed .

FROM public.ecr.aws/lambda/python:3.11

COPY requirements-common.txt requirements-embed.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements-common.txt -r requirements-embed.txt --target ${LAMBDA_TASK_ROOT}

COPY handler.py chunking.py documents.py embedding.py ingest.py podcast_metadata.py store.py transcripts.py youtube_podcast_mapping.json ${LAMBDA_TASK_ROOT}/

CMD ["handler.handler"]
