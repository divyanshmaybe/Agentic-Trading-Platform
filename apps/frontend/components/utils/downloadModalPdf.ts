"use client";

import jsPDF from "jspdf";

export async function downloadCompanyReportPdf() {
	const container = document.getElementById("company-report-pdf");
	if (!container) {
		console.error("PDF root not found");
		return;
	}

	const pdf = new jsPDF("p", "mm", "a4");

	const pageWidth = pdf.internal.pageSize.getWidth();
	const pageHeight = pdf.internal.pageSize.getHeight();

	const margin = 20;
	const contentWidth = pageWidth - margin * 2;
	const lineHeight = 7; // mm per line for normal text

	let cursorY = margin;

	function ensurePageSpace(linesNeeded = 1) {
		if (cursorY + linesNeeded * lineHeight > pageHeight - margin) {
			pdf.addPage();
			cursorY = margin;
		}
	}

	function writeTextBlock(text: string) {
		if (!text.trim()) return;

		const wrapped = pdf.splitTextToSize(text, contentWidth);
		ensurePageSpace(wrapped.length);

		wrapped.forEach((line) => {
			pdf.text(line, margin, cursorY);
			cursorY += lineHeight;
		});
		cursorY += 2;
	}

	function writeHeading(text: string, size: number, bold = false) {
		if (!text.trim()) return;

		pdf.setFontSize(size);
		pdf.setFont("helvetica", bold ? "bold" : "normal");

		const wrapped = pdf.splitTextToSize(text, contentWidth);
		ensurePageSpace(wrapped.length + 1);

		wrapped.forEach((line) => {
			pdf.text(line, margin, cursorY);
			cursorY += lineHeight;
		});

		cursorY += 3;

		// reset default
		pdf.setFontSize(12);
		pdf.setFont("helvetica", "normal");
	}

	function processNode(node: HTMLElement) {
		const tag = node.tagName.toLowerCase();

		if (tag === "h2") {
			writeHeading(node.textContent || "", 18, true);
		} else if (tag === "h3") {
			writeHeading(node.textContent || "", 15, true);
		} else if (tag === "p") {
			writeTextBlock(node.textContent || "");
		} else if (tag === "section") {
			Array.from(node.childNodes).forEach((child) => {
				if (child instanceof HTMLElement) processNode(child);
			});
			cursorY += 2;
		} else {
			// generic fallback for div, spans, etc.
			if (node.childNodes.length === 1 && node.childNodes[0].nodeType === Node.TEXT_NODE) {
				writeTextBlock(node.textContent || "");
			} else {
				Array.from(node.childNodes).forEach((child) => {
					if (child instanceof HTMLElement) processNode(child);
				});
			}
		}
	}

	// Clone modal content but remove the "Download PDF" button
	const cloned = container.cloneNode(true) as HTMLElement;
	cloned.querySelectorAll("button").forEach((button) => {
		if (button.textContent?.includes("Download PDF")) {
			button.remove();
		}
	});

	// Start normal font
	pdf.setFont("helvetica", "normal");
	pdf.setFontSize(12);

	Array.from(cloned.children).forEach((child) => {
		if (child instanceof HTMLElement) {
			processNode(child);
		}
	});

	pdf.save("company-report.pdf");
}
