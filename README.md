# PDF Q&A Bot (RAG Lite)

[![CI](https://github.com/jammiguelyfish/pdf-qna-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/jammiguelyfish/pdf-qna-bot/actions/workflows/ci.yml)

A local, CLI-based PDF Question-Answering application using Retrieval Augmented Generation (RAG). This bot ingests PDF documents, stores embeddings locally, and answers questions strictly from the provided documents to avoid hallucinations.

## Features

- **100% Local**
- **Free & Open Source**: Uses only open-source tools and models
- **Persistent Storage**: Vector embeddings stored locally in Chroma DB
- **Source Attribution**: Shows which PDF and page number the answer came from
- **Hybrid Retrieval**: Embedding search fused with BM25 keyword search, so exact names and date spellings ("Busan", "January 15" vs "Jan 15") are found too

## Tech Stack

- **Python 3.10+**
- **LangChain**
- **Chroma**
- **SentenceTransformers**: Embeddings (all-MiniLM-L6-v2)
- **rank-bm25**: Keyword retrieval, fused with the embeddings
- **Mistral**: LLM via Ollama (local inference)

## Prerequisites

### 1. Python 3.10 or higher

### 2. Ollama

Ollama must be installed and running to use the Mistral model locally.

**Install Ollama:**
- **Windows/Mac/Linux**: Download from [https://ollama.com/download](https://ollama.com/download)

**Verify Ollama is running:**
```bash
ollama --version
```

**Pull the Mistral model:**
```bash
ollama pull mistral
```

This downloads the Mistral model (~4.1GB). It only needs to be done once.

## Setup

### 1. Clone or navigate to project directory

```bash
cd pdf_qa_bot
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv venv
```

**Activate the virtual environment:**
- **Windows**:
  ```bash
  venv\Scripts\activate
  ```
- **Mac/Linux**:
  ```bash
  source venv/bin/activate
  ```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `langchain` and `langchain-community`
- `chromadb` (vector database)
- `sentence-transformers` (embeddings)
- `pypdf` (PDF parsing)
- `rank-bm25` (keyword search for hybrid retrieval)

## Usage

### Step 1: Add PDFs

Place your PDF files in the `data/pdfs/` directory:

```bash
# Example structure
data/pdfs/
  ├── research_paper.pdf
  ├── user_manual.pdf
  └── sales_report.pdf
```

### Step 2: Ingest PDFs

Run the ingestion script to process PDFs and create the vector database:

```bash
python ingest.py
```

**What it does:**
- Loads all PDFs from `data/pdfs/`
- Splits text into chunks (1000 chars, 200 overlap)
- Generates embeddings using SentenceTransformers
- Stores vectors in `chroma_db/` directory
- Safe to re-run (overwrites existing database)

**Expected output:**
```
Found 3 PDF(s): research_paper.pdf, user_manual.pdf, report.pdf

Loading PDFs...
Loaded 45 page(s) from PDF(s)

Splitting documents into chunks...
Created 127 chunks

Initializing embeddings model (all-MiniLM-L6-v2)...
Embeddings model loaded

Creating/updating Chroma vector database at './chroma_db'...
Vector database created and persisted

Ingestion complete! Processed 3 PDF(s) into 127 searchable chunks.
```

### Step 3: Ask Questions

Run the Q&A script to start asking questions:

```bash
python qa.py
```

**Example interaction** (three sample travel-itinerary PDFs, run with a small local model via `LLM_MODEL=qwen2.5:1.5b-instruct python qa.py`):

```
Loading vector database...
Vector database loaded
Connecting to Ollama (qwen2.5:1.5b-instruct)...
LLM ready

============================================================
PDF Q&A Bot Ready! (Type 'exit' or 'quit' to stop)
============================================================

Your Question: Where are we going on January 15?

Answer:
------------------------------------------------------------
Sagada → Baguio → Manila
------------------------------------------------------------

Sources:
  [1] Philippines 21-Day Travel Itinerary.pdf (Page 4)
  [2] Philippines 21-Day Travel Itinerary.pdf (Page 3)
  [3] Philippines 21-Day Travel Itinerary.pdf (Page 3)
  [4] Philippines 21-Day Travel Itinerary.pdf (Page 2)

============================================================

Your Question: How many nights are we staying in Busan?

Answer:
------------------------------------------------------------
3 nights
------------------------------------------------------------

Sources:
  [1] Philippines 21-Day Travel Itinerary.pdf (Page 1)
  [2] Philippines 21-Day Travel Itinerary.pdf (Page 3)
  [3] South Korea 14-Day Travel Itinerary.pdf (Page 1)
  [4] Philippines 21-Day Travel Itinerary.pdf (Page 3)

============================================================

Your Question: What is the weather like in Paris?

Answer:
------------------------------------------------------------
I don't know based on the provided document.
------------------------------------------------------------

Your Question: exit

Goodbye!
```

Questions the documents cannot answer get the fixed "I don't know" reply instead of a guess.

## How it works

1. `ingest.py` loads the PDFs, splits them into overlapping chunks, embeds them and stores them in Chroma.
2. `retrieval.py` builds a **hybrid retriever**: the question is matched against the chunks by embedding similarity *and* by BM25 keyword score, and the two rankings are merged with reciprocal rank fusion. Month names are normalized (`January` becomes `jan`) so a question matches how dates are written in the PDF.
3. `qa.py` passes the top chunks to the local LLM with a strict prompt that forbids using outside knowledge, then prints the answer and its sources.

Why hybrid? Embeddings alone miss exact names and dates ("Busan", "January 15"). The [Evaluation](#evaluation) below measures how much, and where hybrid does and doesn't help.

## Evaluation

`evaluate.py` scores the bot against 27 hand-written questions over the three sample itineraries (`eval/questions.json`): 24 answerable, 6 of which are paraphrased so they share little wording with the PDF, and 3 whose answer is not in the documents. A unit test checks every expected fact against the PDFs, so the ground truth cannot drift.

```bash
python evaluate.py              # retrieval only, no LLM needed
python evaluate.py --answers    # also grade the answers (needs Ollama)
```

**Retrieval**: is the chunk containing the answer in the top 4? (Dense and BM25 gave identical results in 4 runs; the hybrid varies slightly from run to run, so its numbers are a range.)

| Retriever | Hit rate | MRR |
|---|---|---|
| dense (embeddings only) | 17/24 (71%) | 0.50 |
| BM25 (keywords only) | 23/24 (96%) | 0.78 |
| hybrid (what the bot uses) | 22-23/24 (92-96%) | 0.69-0.73 |

**Answers** with `qwen2.5:1.5b-instruct` and the hybrid retriever: 20/24 answerable questions correct, 2/3 unanswerable questions refused. The full report is in [`eval/results.md`](eval/results.md).

What this shows, and what it doesn't:

- Embeddings alone are the weakest here: they miss exact dates and names, which is most of what people ask about an itinerary.
- Keyword search alone is as good as the hybrid, and ranks the answer higher. These documents are short and keyword-rich, so that is plausible. Hybrid is kept because it should be more robust when a question is worded differently from the document, but this question set cannot prove that, because BM25 also handled the paraphrased questions. The fusion weights were not tuned on this set.
- Of the 4 wrong answers to answerable questions, 2 were retrieval misses and 2 were the small model: it garbled a name ("Seoudong Yonggungsa") and answered "I don't know" although the right chunk was retrieved. One unanswerable question (which airline flies Jeju to Seoul) got an answer anyway. A larger model such as Mistral, the default, should do better but was not run here.
- Small-model answers are not stable either: the order of the retrieved chunks changes between runs, and the 1.5B model answered the Busan question correctly in one run and said "I don't know" in another.
- 27 questions over 3 short PDFs is a sanity check, not a benchmark.


## Configuration

You can modify these settings in the scripts:

### `ingest.py`
- `CHUNK_SIZE = 1000` - Size of text chunks
- `CHUNK_OVERLAP = 200` - Overlap between chunks
- `EMBEDDING_MODEL = "all-MiniLM-L6-v2"` - Embedding model

### `qa.py`
- `LLM_MODEL = "mistral"` - Ollama model name (override with the `LLM_MODEL` environment variable)
- `TOP_K = 4` - Number of chunks passed to the LLM after fusion

## Troubleshooting

### "Error: Vector database not found"
- Run `python ingest.py` first to create the database

### "Error: PDF directory does not exist"
- Make sure you're in the `pdf_qa_bot/` directory when running scripts

### "No PDF files found"
- Add at least one PDF to `data/pdfs/`

### Ollama connection errors
- Ensure Ollama is running: `ollama serve`
- Verify Mistral is installed: `ollama list`
- Pull Mistral if needed: `ollama pull mistral`

### "I don't know based on the provided document"
- The answer isn't in your PDFs
- Try rephrasing your question
- Add more relevant PDFs and re-run ingestion

## Project Structure

```
pdf_qa_bot/
├── ingest.py           # PDF ingestion and embedding script
├── qa.py               # Question-answering CLI script
├── retrieval.py        # Hybrid (embeddings + BM25) retriever
├── evaluate.py         # Retrieval and answer evaluation
├── eval/               # Question set and latest results
├── tests/              # Unit tests (run in CI)
├── requirements.txt    # Python dependencies
├── README.md          # This file
├── data/
│   └── pdfs/          # Place your PDF files here
└── chroma_db/         # Vector database (created after ingestion)
```


## License

This project uses open-source components. Check individual library licenses for details.
