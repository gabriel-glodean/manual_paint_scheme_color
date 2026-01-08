import gradio as gr
from pathlib import Path
from logic import (process_pdf, apply_color_mapping,LocalImageFileRepo)
from local import OcrPageFilter
from logic.parsers import parse_page_list


def colorize(clusters, colors, session):
    extracted_repo = LocalImageFileRepo(Path("../output") / session / "vehicles")
    color_repo =  LocalImageFileRepo(Path("../output") / session / "colorized")
    return apply_color_mapping(clusters, colors, extracted_repo, color_repo)

def process(pdf_file, k, dpi, pages, threshold):
    out_repo = LocalImageFileRepo(Path("../output"))
    preview_path, centroids, uuid_string = process_pdf(pdf_file, k, dpi, out_repo, OcrPageFilter(parse_page_list(pages), threshold))
    return str(preview_path), centroids, uuid_string

#-------------------------------------------------------------
# GRADIO UI
# -------------------------------------------------------------

# Build Gradio interface
with gr.Blocks() as demo:
    gr.Markdown("# 🛠 Model Kit Paint Scheme Extractor")
    pdf_session = gr.State()
    pdf = gr.File(label="Upload Instruction PDF", type="binary")
    K = gr.Slider(1, 50, step=1, value=10, label="Number of clusters")
    pages_of_interest = gr.Textbox(
        label="Comma separated list of pages to consider",
    )
    page_dpi = gr.Slider(100, 400, step=10, value=200, label="DPI to use for processing")
    keyword_threshold = gr.Slider(-1, 40, step=1, value=3, label="Threshold of keywords in pages")
    preview_img = gr.Image(label="Cluster Preview")
    centroid_output = gr.JSON(label="Centroid Grayscale Values")

    process_btn = gr.Button("Extract & Cluster First Vehicle")

    # Color pickers will appear dynamically later
    color_pickers = gr.Group()
    final_output = gr.Gallery(label="Final Colored Vehicle", show_label=True, elem_id="final_gallery")
    apply_btn = gr.Button("Apply Color Mapping")

    # First step
    process_btn.click(
        fn=process,
        inputs=[pdf, K, page_dpi, pages_of_interest, keyword_threshold],
        outputs=[preview_img, centroid_output, pdf_session]
    )

    # Second step: dynamic color pickers (user provides hex)
    cluster_colors = gr.Textbox(
        label="Enter hex colors for gray ranges as comma-separated list (e.g. #C7D7E0(100-123),#3F4A54(124-150),#6F6F78(151-200))"
    )

    apply_btn.click(
        fn=colorize,
        inputs=[K, cluster_colors, pdf_session],
        outputs=final_output
    )

if __name__ == "__main__":
    demo.launch(allowed_paths=[str(Path(__file__).resolve().parents[1] / "output")])