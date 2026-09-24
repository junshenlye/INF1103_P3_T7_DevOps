# Host frontend

This Flask app runs outside Docker and renders data from the local Docker API.
It does not import the assessment core or connect to PostgreSQL directly.

Start Docker first:

```sh
docker compose up --build
```

Then run the frontend from the repository root:

```sh
source .venv/bin/activate
python frontend-demo/app.py
```

Open http://127.0.0.1:5050. The frontend calls
http://127.0.0.1:8000 by default. Override that address with
`STACKPLAN_API_URL` only when required.

The browser uploads an evidence pack directly to the local API and polls a
short-lived progress record. It shows elapsed time, current stage, AI attempt,
validation, record creation, and scheduling progress. Uploaded images are
deleted by the API worker after processing.
