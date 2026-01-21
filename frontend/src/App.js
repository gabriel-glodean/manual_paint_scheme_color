import React, { useState } from "react";
import axios from "axios";
import { API_BASE_URL } from "./config";
import JSZip from "jszip";

function App() {
  const [pdf, setPdf] = useState(null);
  const [pdfUrl, setPdfUrl] = useState("");
  const [K, setK] = useState(10);
  const [dpi, setDpi] = useState(125);
  const [pages, setPages] = useState("");
  const [threshold, setThreshold] = useState(3);
  const [centroids, setCentroids] = useState(null);
  const [session, setSession] = useState(null);
  const [colorInput, setColorInput] = useState("");
  const [gallery, setGallery] = useState([]);
  const [extractedImages, setExtractedImages] = useState([]);
  const [previewImg, setPreviewImg] = useState(null);
  const [s3PdfUri, setS3PdfUri] = useState("");

  // Step 1: File or URL selection
  const handlePdfChange = (e) => setPdf(e.target.files[0]);
  const handlePdfUrlChange = (e) => setPdfUrl(e.target.value);

  // Step 1b: Upload to S3 using signed URL
  const uploadToS3 = async (file) => {
    // Get signed URL from backend
    let res;
    try {
      res = await axios.post(`${API_BASE_URL}/get_signed_url`, {
        filename: file.name,
        content_type: file.type,
      });
    } catch (err) {
      throw err;
    }
    // The backend should return { url, bucket, key }
    const { url, bucket, key } = res.data;
    if (!url || !bucket || !key) {
      throw new Error("Invalid signed URL response from backend");
    }
    // Upload file to S3
    await axios.put(url, file, {
      headers: {
        'Content-Type': file.type
      }
    });
    // Return the S3 URI for later use
    const s3Uri = `s3://${bucket}/${key}`;
    return s3Uri;
  };

  // Step 2: Call process_pdf
  const handleProcessPdf = async () => {
    let pdfPath = pdfUrl;
    if (pdf) {
      pdfPath = await uploadToS3(pdf);
      setS3PdfUri(pdfPath);
    }
    // Call process_pdf with S3 URI or URL
    const res = await axios.post(`${API_BASE_URL}/process_pdf`, {
      pdf_path: pdfPath,
      dpi: dpi,
      pages: pages,
      threshold: threshold,
    });
    setSession(res.data.session);
    // Step 3: Call get_preview
    await handleGetPreview(res.data.images[0], res.data.session);
  };

  // Step 3: Call get_preview
  const handleGetPreview = async (image, sessionId) => {
    const res = await axios.post(`${API_BASE_URL}/preview_image`, {
      image: image,
      clusters: K,
      session: sessionId,
    });
    setCentroids(res.data.centroids);
    // Step 4: Download preview image
    // Assume image path is returned in res.data.images[0]
    const imgRes = await axios.post(
        `${API_BASE_URL}/download_images`,
        { images: [res.data.images[0]], session: sessionId },
        {
            responseType: "blob" ,
            headers: { Accept: "application/x-zip-compressed" }
        }
    );
    console.log(imgRes.data.size, imgRes.data.type);

    // Unzip and extract preview image
    const zip = await JSZip.loadAsync(imgRes.data);
    const files = Object.keys(zip.files);
    if (files.length > 0) {
      const fileData = await zip.files[files[0]].async("base64");
      setPreviewImg(`data:image/png;base64,${fileData}`);
    }
  };

  // Step 5: Call apply_color_mapping
  const handleApply = async () => {
    const res = await axios.post(`${API_BASE_URL}/apply_color_mapping`, {
      clusters: K,
      colors: colorInput,
      session: session,
    });
    // Step 6: Download image zip
    const zipRes = await axios.post(
      `${API_BASE_URL}/download_images`,
      { images: res.data.images,
       session: session,
       folder:"colorized",},
      { responseType: "blob",
        headers: { Accept: "application/x-zip-compressed" }}
    );
    // Unzip and extract images in parallel
    const zip = await JSZip.loadAsync(zipRes.data);
    const imagePromises = Object.keys(zip.files)
      .filter(filename => /\.(png|jpg|jpeg|webp)$/i.test(filename))
      .map(filename =>
        zip.files[filename].async("base64").then(fileData => `data:image/png;base64,${fileData}`)
      );
    const images = await Promise.all(imagePromises);
    setGallery(images);
  };

  return (
    <div style={{ maxWidth: 800, margin: "auto" }}>
      <h1>🛠 Model Kit Paint Scheme Extractor</h1>
      <div>
        <label>Upload Instruction PDF:</label>
        <input type="file" accept="application/pdf" onChange={handlePdfChange} />
      </div>
      <div>
        <label>Or enter PDF URL:</label>
        <input type="text" value={pdfUrl} onChange={handlePdfUrlChange} style={{ width: 400 }} />
      </div>
      <div>
        <label>Number of clusters (K):</label>
        <input type="range" min={1} max={50} value={K} onChange={e => setK(Number(e.target.value))} />
        <span>{K}</span>
      </div>
      <div>
        <label>DPI:</label>
        <input type="range" min={100} max={400} step={10} value={dpi} onChange={e => setDpi(Number(e.target.value))} />
        <span>{dpi}</span>
      </div>
      <div>
        <label>Pages of interest (comma separated):</label>
        <input type="text" value={pages} onChange={e => setPages(e.target.value)} />
      </div>
      <div>
        <label>Keyword threshold:</label>
        <input type="range" min={-1} max={40} value={threshold} onChange={e => setThreshold(Number(e.target.value))} />
        <span>{threshold}</span>
      </div>
      <button onClick={handleProcessPdf} disabled={!pages}>Process PDF</button>
      <div>
        <label>Centroid Grayscale Values:</label>
        <pre>{centroids && JSON.stringify(centroids, null, 2)}</pre>
      </div>
      <div>
        <label>Preview Image:</label>
        {previewImg && <img src={previewImg} alt="Preview" style={{ width: 300, margin: 5 }} />}
      </div>
      <div>
        <label>Enter hex colors for gray ranges (comma-separated eg. #C7D7E0(100-123),#3F4A54(124-150),#6F6F78(151-200)):</label>
        <br />
        <input type="text" value={colorInput} onChange={e => setColorInput(e.target.value)} style={{ width: 600 }} />
      </div>
      <button onClick={handleApply} disabled={!session}>Apply Color Mapping</button>
      <div>
        <label>Final Colored Vehicle Gallery:</label>
        <div style={{ display: "flex", flexWrap: "wrap" }}>
          {gallery.map((img, idx) => (
            <img key={idx} src={img} alt={`Colored Vehicle ${idx + 1}`} style={{ width: 200, margin: 5 }} />
          ))}
        </div>
      </div>
    </div>
  );
}

export default App;

