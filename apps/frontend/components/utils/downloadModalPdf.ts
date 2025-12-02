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

	// Line heights matching CSS leading-relaxed (1.625)
	const normalLineHeight = 6; // mm per line for body text
	const headingLineHeight = 7; // mm per line for headings

	let cursorY = margin;

	function ensurePageSpace(heightNeeded: number) {
		if (cursorY + heightNeeded > pageHeight - margin) {
			pdf.addPage();
			cursorY = margin;
		}
	}

	function writeTextBlock(text: string, fontSize = 11, textColor: [number, number, number] = [64, 64, 64]) {
		if (!text.trim()) return;

		pdf.setFontSize(fontSize);
		pdf.setTextColor(textColor[0], textColor[1], textColor[2]);
		pdf.setFont("helvetica", "normal");

		const wrapped = pdf.splitTextToSize(text, contentWidth);
		ensurePageSpace(wrapped.length * normalLineHeight);

		wrapped.forEach((line: string) => {
			pdf.text(line, margin, cursorY);
			cursorY += normalLineHeight;
		});
	}

	function writeHeading(text: string, level: "title" | "h2" | "h3") {
		if (!text.trim()) return;

		let fontSize = 11;
		let fontStyle: "bold" | "normal" = "bold";
		let textColor: [number, number, number] = [17, 17, 17]; // text-gray-900
		let spacingAfter = 3; // mm

		if (level === "title") {
			// DialogTitle: text-2xl font-bold (24px ≈ 16pt)
			fontSize = 16;
			fontStyle = "bold";
			spacingAfter = 2;
		} else if (level === "h2") {
			// H2: text-xl font-semibold (20px ≈ 14pt)
			fontSize = 14;
			fontStyle = "bold";
			spacingAfter = 3;
		} else if (level === "h3") {
			// H3: text-base font-medium (16px ≈ 11pt)
			fontSize = 11;
			fontStyle = "bold";
			textColor = [31, 31, 31]; // text-gray-800
			spacingAfter = 1;
		}

		pdf.setFontSize(fontSize);
		pdf.setFont("helvetica", fontStyle);
		pdf.setTextColor(textColor[0], textColor[1], textColor[2]);

		const wrapped = pdf.splitTextToSize(text, contentWidth);
		ensurePageSpace(wrapped.length * headingLineHeight + spacingAfter);

		wrapped.forEach((line: string) => {
			pdf.text(line, margin, cursorY);
			cursorY += headingLineHeight;
		});

		cursorY += spacingAfter;
	}

	function writeSubtitle(text: string) {
		if (!text.trim()) return;

		pdf.setFontSize(9); // text-sm
		pdf.setTextColor(107, 107, 107); // text-gray-500
		pdf.setFont("helvetica", "normal");

		const wrapped = pdf.splitTextToSize(text, contentWidth);
		ensurePageSpace(wrapped.length * 5);

		wrapped.forEach((line: string) => {
			pdf.text(line, margin, cursorY);
			cursorY += 5;
		});
	}

	function processDivWithSpacing(node: HTMLElement) {
		// Check if this is a space-y-3 container (subsections within a section)
		if (node.className.includes("space-y-3")) {
			Array.from(node.children).forEach((child, index) => {
				if (child instanceof HTMLElement) {
					processNode(child);
					// Add 3mm spacing between subsections (except after last)
					if (index < node.children.length - 1) {
						cursorY += 3;
					}
				}
			});
		} else {
			// Regular div processing
			Array.from(node.childNodes).forEach((child) => {
				if (child instanceof HTMLElement) processNode(child);
			});
		}
	}

	function processNode(node: HTMLElement) {
		const tag = node.tagName.toLowerCase();

		if (tag === "h2") {
			writeHeading(node.textContent || "", "h2");
		} else if (tag === "h3") {
			writeHeading(node.textContent || "", "h3");
		} else if (tag === "p") {
			// Check text color class
			const isGrayText = node.className.includes("text-gray-700");
			const isSmallText = node.className.includes("text-sm");
			const textColor: [number, number, number] = isGrayText ? [64, 64, 64] : [17, 17, 17];
			const fontSize = isSmallText ? 9 : 11;

			writeTextBlock(node.textContent || "", fontSize, textColor);
			cursorY += 2; // Small gap after paragraphs
		} else if (tag === "section") {
			// Sections have space-y-8 (32px ≈ 8mm between them)
			Array.from(node.childNodes).forEach((child) => {
				if (child instanceof HTMLElement) processNode(child);
			});
			cursorY += 8; // space-y-8 equivalent
		} else if (tag === "div") {
			processDivWithSpacing(node);
		} else {
			// generic fallback
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
	cloned.querySelectorAll("button").forEach((button: HTMLElement) => {
		if (button.textContent?.includes("Download PDF")) {
			button.remove();
		}
	});

	// Extract and render DialogHeader content
	const dialogHeader = cloned.querySelector('[class*="DialogHeader"]') || cloned.querySelector("header");
	if (dialogHeader) {
		const title = dialogHeader.querySelector('[class*="DialogTitle"]') || dialogHeader.querySelector("h2");
		if (title) {
			writeHeading(title.textContent || "", "title");
		}

		// Find ticker subtitle
		const subtitle = dialogHeader.querySelector("p");
		if (subtitle) {
			writeSubtitle(subtitle.textContent || "");
			cursorY += 6; // pb-6 border spacing
		}

		// Remove header from cloned content so it's not processed again
		dialogHeader.remove();
	}

	// Start normal font for body content
	pdf.setFont("helvetica", "normal");
	pdf.setFontSize(11);
	pdf.setTextColor(64, 64, 64); // text-gray-700

	// Process remaining content
	Array.from(cloned.children).forEach((child) => {
		if (child instanceof HTMLElement) {
			processNode(child);
		}
	});

	pdf.save("company-report.pdf");
}
