"""
PDF Question Answering Script
Loads Chroma vector store, retrieves relevant chunks, and answers questions using Mistral via Ollama.
"""

import os
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.llms import Ollama
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate

from retrieval import build_hybrid_retriever

# Configuration
CHROMA_DIR = "./chroma_db"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
LLM_MODEL = os.environ.get("LLM_MODEL", "mistral")
TOP_K = 4


def main():
    """
    Main Q&A pipeline:
    1. Load Chroma vector database
    2. Accept user question
    3. Retrieve relevant chunks
    4. Generate answer using Mistral
    5. Display answer with sources
    """
    
    # Check if Chroma database exists
    if not os.path.exists(CHROMA_DIR):
        print(f"Error: Vector database not found at '{CHROMA_DIR}'.")
        print("Please run ingest.py first to process PDFs.")
        return
    
    print("Loading vector database...")
    
    # Initialize embeddings (must use same model as ingestion)
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={'device': 'cpu'},
        encode_kwargs={'normalize_embeddings': True}
    )
    
    # Load persisted Chroma vector store
    vectorstore = Chroma(
        persist_directory=CHROMA_DIR,
        embedding_function=embeddings
    )
    
    print("Vector database loaded")
    
    # Initialize Ollama with Mistral
    print(f"Connecting to Ollama ({LLM_MODEL})...")
    llm = Ollama(
        model=LLM_MODEL,
        temperature=0
    )
    
    print("LLM ready")
    
    # Define strict RAG prompt to prevent hallucinations
    prompt_template = """You are a helpful assistant that answers questions strictly based on the provided context.

Context from documents:
{context}

User Question: {question}

Instructions:
- Answer ONLY using information from the context above
- Do NOT use any external knowledge
- If the answer is not in the context, respond with exactly: "I don't know based on the provided document."
- Be concise and direct

Answer:"""
    
    PROMPT = PromptTemplate(
        template=prompt_template,
        input_variables=["context", "question"]
    )
    
    # Create retrieval QA chain
    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=build_hybrid_retriever(vectorstore, TOP_K),
        return_source_documents=True,
        chain_type_kwargs={"prompt": PROMPT}
    )
    
    print("\n" + "="*60)
    print("PDF Q&A Bot Ready! (Type 'exit' or 'quit' to stop)")
    print("="*60 + "\n")
    
    # Interactive Q&A loop
    while True:
        # Get user question
        question = input("Your Question: ").strip()
        
        # Check for exit commands
        if question.lower() in ['exit', 'quit', 'q']:
            print("\nGoodbye!")
            break
        
        # Skip empty questions
        if not question:
            continue
        
        print("\n🔍 Searching documents and generating answer...\n")
        
        # Get answer from RAG chain
        result = qa_chain.invoke({"query": question})
        
        # Display answer
        print("Answer:")
        print("-" * 60)
        print(result['result'])
        print("-" * 60)
        
        # Display source documents
        print("\nSources:")
        source_docs = result['source_documents']
        
        if source_docs:
            for i, doc in enumerate(source_docs, 1):
                # Extract metadata
                source = doc.metadata.get('source', 'Unknown')
                page = doc.metadata.get('page', 'N/A')
                if isinstance(page, int):
                    page += 1  # PyPDF page numbers are 0-indexed
                
                # Clean up source path (show just filename)
                source_name = os.path.basename(source)
                
                print(f"  [{i}] {source_name} (Page {page})")
        else:
            print("  No sources found")
        
        print("\n" + "="*60 + "\n")


if __name__ == "__main__":
    main()
