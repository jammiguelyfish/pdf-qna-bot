"""
PDF Ingestion Script
Loads PDFs from data/pdfs/, chunks them, generates embeddings, and stores in Chroma.
"""

import os
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

# Configuration
PDF_DIR = "./data/pdfs"
CHROMA_DIR = "./chroma_db"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def main():
    """
    Main ingestion pipeline:
    1. Load PDFs from directory
    2. Split into chunks
    3. Generate embeddings
    4. Store in Chroma vector database
    """
    
    # Check if PDF directory exists
    if not os.path.exists(PDF_DIR):
        print(f"Error: PDF directory '{PDF_DIR}' does not exist.")
        return
    
    # Check if there are any PDFs
    pdf_files = [f for f in os.listdir(PDF_DIR) if f.endswith('.pdf')]
    if not pdf_files:
        print(f"No PDF files found in '{PDF_DIR}'. Please add PDFs first.")
        return
    
    print(f"Found {len(pdf_files)} PDF(s): {', '.join(pdf_files)}")
    print("\nLoading PDFs...")
    
    # Load all PDFs from directory
    loader = PyPDFDirectoryLoader(PDF_DIR)
    documents = loader.load()
    
    print(f"Loaded {len(documents)} page(s) from PDF(s)")
    
    # Split documents into chunks
    print("\nSplitting documents into chunks...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
    )
    chunks = text_splitter.split_documents(documents)
    
    print(f"Created {len(chunks)} chunks")
    
    # Initialize embeddings model
    print(f"\nInitializing embeddings model ({EMBEDDING_MODEL})...")
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={'device': 'cpu'},
        encode_kwargs={'normalize_embeddings': True}
    )
    
    print("Embeddings model loaded")
    
    # Create or update Chroma vector store
    print(f"\nCreating/updating Chroma vector database at '{CHROMA_DIR}'...")
    
    # If Chroma DB already exists, delete it to start fresh
    if os.path.exists(CHROMA_DIR):
        import shutil
        shutil.rmtree(CHROMA_DIR)
        print("   (Removed existing database)")
    
    # Create new vector store
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=CHROMA_DIR
    )
    
    print("Vector database created and persisted")
    print(f"\nIngestion complete! Processed {len(pdf_files)} PDF(s) into {len(chunks)} searchable chunks.")


if __name__ == "__main__":
    main()
