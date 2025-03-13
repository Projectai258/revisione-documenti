import streamlit as st
import openai
import os
import re
import logging
import io
from bs4 import BeautifulSoup  
import markdown
from docx import Document
from PyPDF2 import PdfReader
from fpdf import FPDF, FPDFException

# Configurazione logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API key hardcoded (ricorda: per produzione è preferibile usare st.secrets)
OPENROUTER_API_KEY = "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"
if not OPENROUTER_API_KEY:
    st.error("⚠️ Errore: API Key di OpenRouter non trovata!")
    logger.error("API Key non trovata. L'applicazione si interrompe.")
    st.stop()

# Inizializza il client OpenAI per OpenRouter
client = openai.OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")

# Pattern critici (pre-compilati per efficienza)
CRITICAL_PATTERNS = [
    r"\bIlias Contreas\b",
    r"\bIlias\b",
    r"\bContreas\b",
    r"\bJoey\b",
    r"\bMya\b",
    r"\bmia moglie\b",
    r"\bmia figlia\b",
    r"\bShake Your English\b",
    r"\bBarman PR\b",
    r"\bStairs Club\b",
    r"\bil mio socio\b",
    r"\bio e il mio socio\b",
    r"\bil mio corso\b",
    r"\bla mia accademia\b",
    r"\bintervista\b",
    r"Mi chiamo .*? la mia esperienza personale\.",
    r"\bflair\b",
    r"\bfiglio di papà\b",
    r"\bhappy our\b",
]
compiled_patterns = [re.compile(p, re.IGNORECASE) for p in CRITICAL_PATTERNS]

# Opzioni di tono (descrizioni per riferimento, non visualizzate interamente)
TONE_OPTIONS = {
    "Stile originale": "Mantieni lo stesso stile, stessa struttura della frase.",
    "Formale": "Riscrivi in modo formale e professionale.",
    "Informale": "Riscrivi in modo amichevole e colloquiale rivolto ad un lettore giovane.",
    "Tecnico": "Riscrivi con linguaggio tecnico e preciso.",
    "Narrativo": "Riscrivi in stile descrittivo e coinvolgente per un pubblico giovanile.",
    "Pubblicitario": "Riscrivi in modo persuasivo, come una pubblicità.",
    "Giornalistico": "Riscrivi in tono chiaro e informativo.",
}

def extract_context(blocks, selected_block):
    """Trova il blocco precedente e successivo per dare contesto."""
    try:
        index = blocks.index(selected_block)
    except ValueError:
        logger.error("Il blocco selezionato non è presente nella lista.")
        return "", ""
    prev_block = blocks[index - 1] if index > 0 else ""
    next_block = blocks[index + 1] if index < len(blocks) - 1 else ""
    return prev_block, next_block

def ai_rewrite_text(text, prev_text, next_text, tone):
    """Invia il prompt all'API per riscrivere il testo."""
    prompt = (
        f"Context:\nPreceding: {prev_text}\nText: {text}\nFollowing: {next_text}\n\n"
        f"Rewrite the 'Text' in {tone} style. Remove any personal or identifiable details. "
        f"Return only ONE sentence with no additional commentary."
    )
    try:
        response = client.chat.completions.create(
            model="google/gemini-exp-1206:free",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=50
        )
        if response and hasattr(response, "choices") and response.choices:
            result = response.choices[0].message.content.strip()
            return result if result else text  # se vuoto, ritorna il testo originale
        else:
            error_message = "⚠️ Errore: Nessun testo valido restituito dall'API."
            logger.error(error_message)
            return text
    except Exception as e:
        error_message = f"⚠️ Errore nell'elaborazione: {e}"
        logger.error(error_message)
        return text

def process_html_content(html_content, modifications, highlight=False):
    """Sostituisce i blocchi modificati nel contenuto HTML."""
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup.find_all(["p", "span", "div", "li", "a", "h5"]):
        if tag.string:
            original = tag.string.strip()
            if original in modifications:
                mod_text = modifications[original]
                if highlight:
                    new_tag = soup.new_tag("span", style="background-color: yellow; font-weight: bold;")
                    new_tag.string = mod_text
                    tag.string.replace_with("")
                    tag.append(new_tag)
                else:
                    tag.string.replace_with(mod_text)
    return str(soup)

def generate_html_preview(blocks, modifications, highlight=False):
    """Genera un'anteprima in HTML da una lista di blocchi."""
    html = ""
    for block in blocks:
        mod_text = modifications.get(block, block)
        if highlight:
            html += f'<p><span style="background-color: yellow; font-weight: bold;">{mod_text}</span></p>'
        else:
            html += f"<p>{mod_text}</p>"
    return html

# Impostazione pagina
st.set_page_config(page_title="Revisione Documenti", layout="wide")
st.title("📄 Revisione Documenti")
st.write("Carica un file (HTML, Markdown, Word o PDF) e scegli i blocchi da revisionare.")

# Caricamento file
uploaded_file = st.file_uploader("📂 Seleziona un file (html, md, doc, docx, pdf)", type=["html", "md", "doc", "docx", "pdf"])

if uploaded_file is not None:
    file_extension = uploaded_file.name.split('.')[-1].lower()
    modifications = {}
    
    if file_extension in ["html", "md"]:
        file_content = uploaded_file.read().decode("utf-8")
        html_content = file_content if file_extension == "html" else markdown.markdown(file_content)
        soup = BeautifulSoup(html_content, "html.parser")
        blocks = [tag.string.strip() for tag in soup.find_all(["p", "span", "div", "li", "a", "h5"]) if tag.string]
        blocks_to_review = {f"{i}_{b}": b for i, b in enumerate(blocks) if any(pattern.search(b) for pattern in compiled_patterns)}
        
        if blocks_to_review:
            st.subheader("📌 Blocchi da revisionare")
            progress_text = st.empty()
            progress_bar = st.progress(0)
            total = len(blocks_to_review)
            count = 0
            for uid, block in blocks_to_review.items():
                st.markdown(f"**{block}**")
                action = st.radio(f"Azione per:", ["Riscrivi", "Elimina", "Ignora"], key=f"action_{uid}")
                if action == "Riscrivi":
                    selected_tone = st.selectbox("Scegli il tono:", list(TONE_OPTIONS.keys()), key=f"tone_{uid}")
                    prev_block, next_block = extract_context(blocks, block)
                    attempts = 0
                    mod_block = ""
                    while attempts < 3:
                        mod_block = ai_rewrite_text(block, prev_block, next_block, selected_tone)
                        if mod_block and "Errore" not in mod_block:
                            break
                        attempts += 1
                    modifications[block] = mod_block if mod_block.strip() else block
                elif action == "Elimina":
                    modifications[block] = ""
                elif action == "Ignora":
                    modifications[block] = block
                count += 1
                progress_bar.progress(count / total)
                progress_text.text(f"Elaborati {count} di {total} blocchi...")
            
            if st.button("✍️ Genera Documento Revisionato"):
                with st.spinner("🔄 Riscrittura in corso..."):
                    preview_html = process_html_content(html_content, modifications, highlight=True)
                    final_html = process_html_content(html_content, modifications, highlight=False)
                    st.session_state["preview_content"] = preview_html
                    st.session_state["final_content"] = final_html
                st.success("✅ Revisione completata!")
                st.subheader("🌍 Anteprima con Testo Formattato")
                st.markdown(st.session_state["preview_content"], unsafe_allow_html=True)
                st.download_button("📥 Scarica HTML Revisionato", st.session_state["final_content"].encode("utf-8"), "document_revised.html", "text/html")
        else:
            st.info("Non sono state trovate corrispondenze per i criteri di ricerca nel testo.")
    
    elif file_extension in ["doc", "docx"]:
        try:
            doc = Document(uploaded_file)
        except Exception as e:
            st.error(f"Errore nell'apertura del file Word: {e}")
            st.stop()
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        blocks_to_review = {f"{i}_{p}": p for i, p in enumerate(paragraphs) if any(pattern.search(p) for pattern in compiled_patterns)}
        
        if blocks_to_review:
            st.subheader("📌 Paragrafi da revisionare")
            progress_text = st.empty()
            progress_bar = st.progress(0)
            total = len(blocks_to_review)
            count = 0
            for uid, paragraph in blocks_to_review.items():
                st.markdown(f"**{paragraph}**")
                action = st.radio(f"Azione per:", ["Riscrivi", "Elimina", "Ignora"], key=f"action_{uid}")
                if action == "Riscrivi":
                    selected_tone = st.selectbox("Scegli il tono:", list(TONE_OPTIONS.keys()), key=f"tone_{uid}")
                    prev_par, next_par = extract_context(paragraphs, paragraph)
                    attempts = 0
                    mod_par = ""
                    while attempts < 3:
                        mod_par = ai_rewrite_text(paragraph, prev_par, next_par, selected_tone)
                        if mod_par and "Errore" not in mod_par:
                            break
                        attempts += 1
                    modifications[paragraph] = mod_par if mod_par.strip() else paragraph
                elif action == "Elimina":
                    modifications[paragraph] = ""
                elif action == "Ignora":
                    modifications[paragraph] = paragraph
                count += 1
                progress_bar.progress(count / total)
                progress_text.text(f"Elaborati {count} di {total} paragrafi...")
            
            if st.button("✍️ Genera Documento Word Revisionato"):
                with st.spinner("🔄 Riscrittura in corso..."):
                    new_doc = Document()
                    for par in paragraphs:
                        new_doc.add_paragraph(modifications.get(par, par))
                    buffer = io.BytesIO()
                    new_doc.save(buffer)
                    st.session_state["final_docx"] = buffer.getvalue()
                    preview_html = generate_html_preview(paragraphs, modifications, highlight=True)
                st.success("✅ Revisione completata!")
                st.subheader("🌍 Anteprima con Testo Formattato")
                st.markdown(preview_html, unsafe_allow_html=True)
                st.download_button("📥 Scarica Documento Word Revisionato", st.session_state["final_docx"], "document_revised.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        else:
            st.info("Non sono state trovate corrispondenze per i criteri di ricerca nel documento Word.")
    
    elif file_extension == "pdf":
        try:
            pdf_reader = PdfReader(uploaded_file)
        except Exception as e:
            st.error(f"Errore nell'apertura del file PDF: {e}")
            st.stop()
        paragraphs = []
        for page in pdf_reader.pages:
            text = page.extract_text()
            if text:
                paragraphs.extend([line.strip() for line in text.split("\n") if line.strip()])
        blocks_to_review = {f"{i}_{p}": p for i, p in enumerate(paragraphs) if any(pattern.search(p) for pattern in compiled_patterns)}
        
        if blocks_to_review:
            st.subheader("📌 Blocchi di testo da revisionare (PDF)")
            progress_text = st.empty()
            progress_bar = st.progress(0)
            total = len(blocks_to_review)
            count = 0
            for uid, block in blocks_to_review.items():
                st.markdown(f"**{block}**")
                action = st.radio(f"Azione per:", ["Riscrivi", "Elimina", "Ignora"], key=f"action_{uid}")
                if action == "Riscrivi":
                    selected_tone = st.selectbox("Scegli il tono:", list(TONE_OPTIONS.keys()), key=f"tone_{uid}")
                    prev_block, next_block = extract_context(paragraphs, block)
                    attempts = 0
                    mod_block = ""
                    while attempts < 3:
                        mod_block = ai_rewrite_text(block, prev_block, next_block, selected_tone)
                        if mod_block and "Errore" not in mod_block:
                            break
                        attempts += 1
                    modifications[block] = mod_block if mod_block.strip() else block
                elif action == "Elimina":
                    modifications[block] = ""
                elif action == "Ignora":
                    modifications[block] = block
                count += 1
                progress_bar.progress(count / total)
                progress_text.text(f"Elaborati {count} di {total} blocchi...")
            
            if st.button("✍️ Genera PDF Revisionato"):
                with st.spinner("🔄 Riscrittura in corso..."):
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_auto_page_break(auto=True, margin=15)
                    pdf.set_font("Arial", size=12)
                    for par in paragraphs:
                        text_to_print = modifications.get(par, par)
                        # Salta se il testo è vuoto o troppo lungo senza spazi
                        if not text_to_print.strip():
                            continue
                        try:
                            pdf.multi_cell(0, 10, text_to_print)
                        except FPDFException as e:
                            logger.error(f"Errore FPDF per il paragrafo: {text_to_print} - {e}")
                    pdf_buffer = io.BytesIO()
                    pdf.output(pdf_buffer, 'F')
                    st.session_state["final_pdf"] = pdf_buffer.getvalue()
                    preview_html = generate_html_preview(paragraphs, modifications, highlight=True)
                st.success("✅ Revisione completata!")
                st.subheader("🌍 Anteprima con Testo Formattato")
                st.markdown(preview_html, unsafe_allow_html=True)
                st.download_button("📥 Scarica PDF Revisionato", st.session_state["final_pdf"], "document_revised.pdf", "application/pdf")
        else:
            st.info("Non sono state trovate corrispondenze per i criteri di ricerca nel documento PDF.")
