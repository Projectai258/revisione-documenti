import streamlit as st
import openai
import os
import re
import logging
import io
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import markdown
from docx import Document
from PyPDF2 import PdfReader
from fpdf import FPDF

########################################
# 1) Carica variabili d'ambiente (solo Python)
########################################
load_dotenv()

########################################
# 2) PRIMO comando Streamlit
########################################
st.set_page_config(page_title="Revisione Documenti", layout="wide")

########################################
# 3) Configurazione logging e altre impostazioni Python
########################################
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

########################################
# 4) Recupera la chiave API
########################################
API_KEY = os.getenv("OPENROUTER_API_KEY") or st.secrets.get("OPENROUTER_API_KEY")
if not API_KEY:
    st.error("⚠️ Errore: API Key di OpenRouter non trovata! Impostala come variabile d'ambiente o in st.secrets.")
    st.stop()

# Inizializza il client OpenAI per OpenRouter
client = openai.OpenAI(api_key=API_KEY, base_url="https://openrouter.ai/api/v1")

########################################
# Definizione dei pattern critici
########################################
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

########################################
# Opzioni di tono per la riscrittura
########################################
TONE_OPTIONS = {
    "Stile originale": "Mantieni lo stesso stile del testo originale, stessa struttura della frase.",
    "Formale": "Riscrivi in modo formale e professionale.",
    "Informale": "Riscrivi in modo amichevole e colloquiale rivolto ad un lettore giovane.",
    "Tecnico": "Riscrivi con linguaggio tecnico e preciso.",
    "Narrativo": "Riscrivi in stile descrittivo e coinvolgente direzionato ad un pubblico giovanile.",
    "Pubblicitario": "Riscrivi in modo persuasivo, come una pubblicità.",
    "Giornalistico": "Riscrivi in tono chiaro e informativo.",
}

########################################
# Funzioni di supporto
########################################
def extract_context(blocks, selected_block):
    """Estrae il blocco precedente e successivo per fornire contesto al modello."""
    try:
        index = blocks.index(selected_block)
    except ValueError:
        logger.error("Il blocco selezionato non è presente nella lista.")
        return "", ""
    prev_block = blocks[index - 1] if index > 0 else ""
    next_block = blocks[index + 1] if index < len(blocks) - 1 else ""
    return prev_block, next_block

def ai_rewrite_text(text, prev_text, next_text, tone):
    """Richiede all'API di riscrivere il testo in base al tono selezionato."""
    prompt = (
        f"Contesto:\nPrecedente: {prev_text}\nTesto: {text}\nSuccessivo: {next_text}\n\n"
        f"Riscrivi il 'Testo' in tono '{tone}'. Rimuovi eventuali dettagli personali o identificabili. "
        "Rispondi con UNA sola frase, senza ulteriori commenti."
    )
    try:
        response = client.chat.completions.create(
            model="google/gemini-2.0-pro-exp-02-05:free",  # o qualunque altro modello tu voglia
            messages=[{"role": "system", "content": prompt}],
            max_tokens=50
        )
        if response and hasattr(response, "choices") and response.choices:
            return response.choices[0].message.content.strip()
        error_message = "⚠️ Errore: Nessun testo valido restituito dall'API."
        logger.error(error_message)
        return error_message
    except Exception as e:
        error_message = f"⚠️ Errore nell'elaborazione: {e}"
        logger.error(error_message)
        return error_message

def process_html_content(html_content, modifications, highlight=False):
    """Sostituisce i blocchi modificati all'interno del contenuto HTML."""
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
    """Genera un'anteprima HTML evidenziata."""
    html = ""
    for block in blocks:
        mod_text = modifications.get(block, block)
        if highlight:
            html += f'<p><span style="background-color: yellow; font-weight: bold;">{mod_text}</span></p>'
        else:
            html += f"<p>{mod_text}</p>"
    return html

def process_file_content(file_content, file_extension):
    """Elabora il contenuto in base al tipo di file e ritorna (lista_blocchi, contenuto_html)."""
    if file_extension == "html":
        html_content = file_content
    elif file_extension == "md":
        html_content = markdown.markdown(file_content)
    else:
        html_content = ""
    if html_content:
        soup = BeautifulSoup(html_content, "html.parser")
        blocks = [tag.string.strip() for tag in soup.find_all(["p", "span", "div", "li", "a", "h5"]) if tag.string]
        return blocks, html_content
    return [], ""

def process_doc_file(uploaded_file):
    """Estrae i paragrafi da un file Word."""
    try:
        doc = Document(uploaded_file)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return paragraphs
    except Exception as e:
        st.error(f"Errore nell'apertura del file Word: {e}")
        st.stop()

def process_pdf_file(uploaded_file):
    """Estrae il testo da un file PDF."""
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
    return paragraphs

def filtra_blocchi(blocchi):
    """Filtra i blocchi che corrispondono a uno dei pattern critici."""
    return {f"{i}_{b}": b for i, b in enumerate(blocchi) if any(pattern.search(b) for pattern in compiled_patterns)}

########################################
# 5) Ora logica principale Streamlit
########################################

st.title("📄 Revisione Documenti")
st.write("Carica un file (HTML, Markdown, Word o PDF) e scegli i blocchi di testo da revisionare.")

uploaded_file = st.file_uploader("📂 Seleziona un file (html, md, doc, docx, pdf)", type=["html", "md", "doc", "docx", "pdf"])

if uploaded_file is not None:
    file_extension = uploaded_file.name.split('.')[-1].lower()
    modifications = {}
    
    if file_extension in ["html", "md"]:
        # Elaborazione per HTML e Markdown
        file_content = uploaded_file.read().decode("utf-8")
        blocchi, html_content = process_file_content(file_content, file_extension)
        blocchi_da_revisionare = filtra_blocchi(blocchi)
        
        if blocchi_da_revisionare:
            st.subheader("📌 Blocchi da revisionare")
            progress_text = st.empty()
            progress_bar = st.progress(0)
            total = len(blocchi_da_revisionare)
            count = 0
            for uid, blocco in blocchi_da_revisionare.items():
                st.markdown(f"**{blocco}**")
                azione = st.radio("Azione per questo blocco:", ["Riscrivi", "Elimina", "Ignora"], key=f"action_{uid}")
                if azione == "Riscrivi":
                    tono = st.selectbox("Scegli il tono:", list(TONE_OPTIONS.keys()), key=f"tone_{uid}")
                    prev_blocco, next_blocco = extract_context(blocchi, blocco)
                    attempts = 0
                    mod_blocco = ""
                    while attempts < 3:
                        mod_blocco = ai_rewrite_text(blocco, prev_blocco, next_blocco, tono)
                        if "Errore" not in mod_blocco:
                            break
                        attempts += 1
                    modifications[blocco] = mod_blocco
                elif azione == "Elimina":
                    modifications[blocco] = ""
                else:
                    modifications[blocco] = blocco
                count += 1
                progress_bar.progress(count / total)
                progress_text.text(f"Elaborati {count} di {total} blocchi...")
            
            if st.button("✍️ Genera Documento Revisionato"):
                with st.spinner("🔄 Riscrittura in corso..."):
                    st.session_state["preview_content"] = process_html_content(html_content, modifications, highlight=True)
                    st.session_state["final_content"] = process_html_content(html_content, modifications, highlight=False)
                st.success("✅ Revisione completata!")
                st.subheader("🌍 Anteprima con Testo Evidenziato")
                st.components.v1.html(st.session_state["preview_content"], height=500, scrolling=True)
                st.download_button("📥 Scarica HTML Revisionato", st.session_state["final_content"].encode("utf-8"), "document_revised.html", "text/html")
        else:
            st.info("Non sono state trovate corrispondenze per i criteri di ricerca nel testo.")
    
    elif file_extension in ["doc", "docx"]:
        # Elaborazione per file Word
        paragrafi = process_doc_file(uploaded_file)
        blocchi_da_revisionare = filtra_blocchi(paragrafi)
        
        if blocchi_da_revisionare:
            st.subheader("📌 Paragrafi da revisionare")
            progress_text = st.empty()
            progress_bar = st.progress(0)
            total = len(blocchi_da_revisionare)
            count = 0
            for uid, paragrafo in blocchi_da_revisionare.items():
                st.markdown(f"**{paragrafo}**")
                azione = st.radio("Azione per questo paragrafo:", ["Riscrivi", "Elimina", "Ignora"], key=f"action_{uid}")
                if azione == "Riscrivi":
                    tono = st.selectbox("Scegli il tono:", list(TONE_OPTIONS.keys()), key=f"tone_{uid}")
                    prev_par, next_par = extract_context(paragrafi, paragrafo)
                    attempts = 0
                    mod_par = ""
                    while attempts < 3:
                        mod_par = ai_rewrite_text(paragrafo, prev_par, next_par, tono)
                        if "Errore" not in mod_par:
                            break
                        attempts += 1
                    modifications[paragrafo] = mod_par
                elif azione == "Elimina":
                    modifications[paragrafo] = ""
                else:
                    modifications[paragrafo] = paragrafo
                count += 1
                progress_bar.progress(count / total)
                progress_text.text(f"Elaborati {count} di {total} paragrafi...")
            
            if st.button("✍️ Genera Documento Word Revisionato"):
                with st.spinner("🔄 Riscrittura in corso..."):
                    nuovo_doc = Document()
                    for par in paragrafi:
                        nuovo_doc.add_paragraph(modifications.get(par, par))
                    buffer = io.BytesIO()
                    nuovo_doc.save(buffer)
                    st.session_state["final_docx"] = buffer.getvalue()
                    preview_html = generate_html_preview(paragrafi, modifications, highlight=True)
                st.success("✅ Revisione completata!")
                st.subheader("🌍 Anteprima con Testo Evidenziato")
                st.components.v1.html(preview_html, height=500, scrolling=True)
                st.download_button("📥 Scarica Documento Word Revisionato", st.session_state["final_docx"], "document_revised.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        else:
            st.info("Non sono state trovate corrispondenze per i criteri di ricerca nel documento Word.")
    
    elif file_extension == "pdf":
        # Elaborazione per file PDF
        paragrafi = process_pdf_file(uploaded_file)
        blocchi_da_revisionare = filtra_blocchi(paragrafi)
        
        if blocchi_da_revisionare:
            st.subheader("📌 Blocchi di testo da revisionare (PDF)")
            progress_text = st.empty()
            progress_bar = st.progress(0)
            total = len(blocchi_da_revisionare)
            count = 0
            for uid, blocco in blocchi_da_revisionare.items():
                st.markdown(f"**{blocco}**")
                azione = st.radio("Azione per questo blocco:", ["Riscrivi", "Elimina", "Ignora"], key=f"action_{uid}")
                if azione == "Riscrivi":
                    tono = st.selectbox("Scegli il tono:", list(TONE_OPTIONS.keys()), key=f"tone_{uid}")
                    prev_blocco, next_blocco = extract_context(paragrafi, blocco)
                    attempts = 0
                    mod_blocco = ""
                    while attempts < 3:
                        mod_blocco = ai_rewrite_text(blocco, prev_blocco, next_blocco, tono)
                        if "Errore" not in mod_blocco:
                            break
                        attempts += 1
                    modifications[blocco] = mod_blocco
                elif azione == "Elimina":
                    modifications[blocco] = ""
                else:
                    modifications[blocco] = blocco
                count += 1
                progress_bar.progress(count / total)
                progress_text.text(f"Elaborati {count} di {total} blocchi...")
            
            if st.button("✍️ Genera PDF Revisionato"):
                with st.spinner("🔄 Riscrittura in corso..."):
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_auto_page_break(auto=True, margin=15)
                    pdf.set_font("Arial", size=12)
                    for par in paragrafi:
                        pdf.multi_cell(0, 10, modifications.get(par, par))
                    pdf_buffer = io.BytesIO()
                    pdf.output(pdf_buffer, 'F')
                    st.session_state["final_pdf"] = pdf_buffer.getvalue()
                    preview_html = generate_html_preview(paragrafi, modifications, highlight=True)
                st.success("✅ Revisione completata!")
                st.subheader("🌍 Anteprima con Testo Evidenziato")
                st.components.v1.html(preview_html, height=500, scrolling=True)
                st.download_button("📥 Scarica PDF Revisionato", st.session_state["final_pdf"], "document_revised.pdf", "application/pdf")
        else:
            st.info("Non sono state trovate corrispondenze per i criteri di ricerca nel documento PDF.")
