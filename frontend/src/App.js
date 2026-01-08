import React, { useState } from "react";
import axios from "axios";
import { API_BASE_URL } from "./config";
import JSZip from "jszip";

function App() {
  const [pdf, setPdf] = useState(null);
  const [K, setK] = useState(10);
  const [dpi, setDpi] = useState(200);
  const [pages, setPages] = useState("");
  const [threshold, setThreshold] = useState(3);
  const [centroids, setCentroids] = useState(null);
  const [session, setSession] = useState(null);
  const [colorInput, setColorInput] = useState("");
  const [gallery, setGallery] = useState([]);
  const [extractedImages, setExtractedImages] = useState([]);

  const handlePdfChange = (e) => setPdf(e.target.files[0]);

  // New handler for Extract
  const handleExtract = async () => {
    const formData = new FormData();
    formData.append("pdf_file", pdf);
    formData.append("clusters", K);
    formData.append("dpi", dpi);
    formData.append("pages", pages);
    formData.append("threshold", threshold);

    // First: process_pdf
    const res = await axios.post(`${API_BASE_URL}/process_pdf`, formData);
    setCentroids(res.data.centroids);
    setSession(res.data.session);

    // Second: download_images (expecting zip file)
    const zipRes = await axios.post(
      `${API_BASE_URL}/download_images`,
      { images: res.data.images },
      { responseType: "blob" }
    );

    // Unzip and extract images in parallel
    const zip = await JSZip.loadAsync(zipRes.data);
    const imagePromises = Object.keys(zip.files)
      .filter(filename => /\.(png|jpg|jpeg)$/i.test(filename))
      .map(filename =>
        zip.files[filename].async("base64").then(fileData => `data:image/png;base64,${fileData}`)
      );
    const images = await Promise.all(imagePromises);
    setExtractedImages(images);
  };

  const handleApply = async () => {
    const formData = new FormData();
    formData.append("clusters", K);
    formData.append("colors", colorInput);
    formData.append("session", session);
    // Request zip file from backend
    const colors = await axios.post(
      `${API_BASE_URL}/apply_color_mapping`,
      formData
    );

    // Second: download_images (expecting zip file)
    const zipRes = await axios.post(
      `${API_BASE_URL}/download_images`,
      { images: colors.data.images },
      { responseType: "blob" }
    );

    // Unzip and extract images in parallel
    const zip = await JSZip.loadAsync(zipRes.data);
    const imagePromises = Object.keys(zip.files)
      .filter(filename => /\.(png|jpg|jpeg)$/i.test(filename))
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
      <button onClick={handleExtract}>Extract</button>
      <div>
        <label>Centroid Grayscale Values:</label>
        <pre>{centroids && JSON.stringify(centroids, null, 2)}</pre>
      </div>
      <div>
        <label>Extracted Images:</label>
        <div style={{ display: "flex", flexWrap: "wrap" }}>
          {extractedImages.map((img, idx) => (
            <img key={idx} src={img} alt={`Extracted ${idx + 1}`} style={{ width: 200, margin: 5 }} />
          ))}
        </div>
      </div>
      <div>
        <label>Enter hex colors for gray ranges (comma-separated):</label>
        <input type="text" value={colorInput} onChange={e => setColorInput(e.target.value)} />
      </div>
      <button onClick={handleApply}>Apply Color Mapping</button>
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

