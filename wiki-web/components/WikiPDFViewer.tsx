'use client';

import { useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface WikiPDFViewerProps {
    base64: string;
}

export default function WikiPDFViewer({ base64 }: WikiPDFViewerProps) {
    const [numPages, setNumPages] = useState<number>(0);

    const pdfData = base64.startsWith('data:')
        ? base64
        : `data:application/pdf;base64,${base64}`;

    return (
        <div style={{
            width: '100%',
            height: '100%',
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 16,
            padding: '16px 0',
            background: '#f0f5ef',
            borderRadius: 12,
        }}>
            <Document
                file={pdfData}
                onLoadSuccess={({ numPages }) => setNumPages(numPages)}
            >
                {Array.from({ length: numPages }, (_, i) => (
                    <Page
                        key={i + 1}
                        pageNumber={i + 1}
                        width={Math.min(800, window.innerWidth - 360)}
                        renderTextLayer
                        renderAnnotationLayer
                    />
                ))}
            </Document>
        </div>
    );
}
