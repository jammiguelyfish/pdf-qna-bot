# PDF Q&A Bot (RAG Lite)

A local, CLI-based PDF Question-Answering application using Retrieval Augmented Generation (RAG). This bot ingests PDF documents, stores embeddings locally, and answers questions strictly from the provided documents to avoid hallucinations.

## Features

- **100% Local**: No cloud APIs, all processing happens on your machine
- **Free & Open Source**: Uses only open-source tools and models
- **Hallucination Prevention**: Strict RAG prompting ensures answers come only from documents
- **Persistent Storage**: Vector embeddings stored locally in Chroma DB
- **Source Attribution**: Shows which PDF and page number the answer came from

## Tech Stack

- **Python 3.10+**
- **LangChain**: RAG orchestration
- **Chroma**: Local vector database
- **SentenceTransformers**: Embeddings (all-MiniLM-L6-v2)
- **Mistral**: LLM via Ollama (local inference)

## Prerequisites

### 1. Python 3.10 or higher

Check your Python version:
```bash
python --version
```

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

## Usage

### Step 1: Add PDFs

Place your PDF files in the `data/pdfs/` directory:

```bash
# Example structure
data/pdfs/
  ├── research_paper.pdf
  ├── user_manual.pdf
  └── report.pdf
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

**Example interaction:**

```
Loading vector database...
Vector database loaded
Connecting to Ollama (mistral)...
LLM ready

============================================================
PDF Q&A Bot Ready! (Type 'exit' or 'quit' to stop)
============================================================

Your Question: What is the main conclusion of the research paper?

Searching documents and generating answer...

Answer:
------------------------------------------------------------
The main conclusion is that the proposed method improves 
accuracy by 15% compared to baseline approaches while 
maintaining computational efficiency.
------------------------------------------------------------

Sources:
  [1] research_paper.pdf (Page 12)
  [2] research_paper.pdf (Page 11)

============================================================

Your Question: exit

Goodbye!
```

## Configuration

You can modify these settings in the scripts:

### `ingest.py`
- `CHUNK_SIZE = 1000` - Size of text chunks
- `CHUNK_OVERLAP = 200` - Overlap between chunks
- `EMBEDDING_MODEL = "all-MiniLM-L6-v2"` - Embedding model

### `qa.py`
- `LLM_MODEL = "mistral"` - Ollama model name
- `TOP_K = 4` - Number of chunks to retrieve

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
├── requirements.txt    # Python dependencies
├── README.md          # This file
├── data/
│   └── pdfs/          # Place your PDF files here
└── chroma_db/         # Vector database (created after ingestion)
```


## License

This project uses open-source components. Check individual library licenses for details.
