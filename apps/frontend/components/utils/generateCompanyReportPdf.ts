"use client";

import jsPDF from "jspdf";

interface CompanyReport {
  [key: string]: any;
}

export function generateCompanyReportPdf(report: CompanyReport) {
  if (!report) return;

  const pdf = new jsPDF("p", "mm", "a4");

  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();

  const margin = 10;
  const contentWidth = pageWidth - margin * 2;

  let cursorY = margin;

  const clean = (str: string): string =>
    str
      .normalize("NFKC")
      .replace(/[\u200B-\u200D\u2060\uFEFF]/g, "")
      .replace(/[\u00A0]/g, " ")
      .replace(/\s+/g, " ")
	.replace(/₹/g, "INR ")
      .trim();

  const ensureSpace = (needed: number) => {
    if (cursorY + needed > pageHeight - margin) {
      pdf.addPage();
      cursorY = margin;
    }
  };

  const writeHeading = (text: string, size = 18) => {
    text = clean(text);
    pdf.setFont("helvetica", "bold");
    pdf.setFontSize(size);

    const lineHeight = size * 0.55;
    const lines = pdf.splitTextToSize(text, contentWidth);

    ensureSpace(lines.length * lineHeight);
    lines.forEach((line) => {
      pdf.text(line, margin, cursorY);
      cursorY += lineHeight;
    });
    cursorY += 4;
  };

	const writeSubheading = (text: string) => {
		text = clean(text);
		pdf.setFont("helvetica", "bold");
		pdf.setFontSize(15);

		const lines = pdf.splitTextToSize(text, contentWidth);
		const lineHeight = 8;

		for (const line of lines) {
			if (cursorY + lineHeight > pageHeight - margin) {
				pdf.addPage();
				cursorY = margin;
			}
			pdf.text(line, margin, cursorY);
			cursorY += lineHeight;
		}

		cursorY += 1; // reduced padding
	};

	const writeParagraph = (text: string) => {
		text = clean(text);
		pdf.setFont("helvetica", "normal");
		pdf.setFontSize(12);

		const lines = pdf.splitTextToSize(text, contentWidth);
		const lineHeight = 6;

		for (const line of lines) {
			if (cursorY + lineHeight > pageHeight - margin) {
				pdf.addPage();
				cursorY = margin;
			}
			pdf.text(line, margin, cursorY);
			cursorY += lineHeight;
		}

		cursorY += 2; // Small padding after paragraph
	};



  writeHeading(report.company_name || report.ticker);

  const sections = [
    ["company_description", "Company Description"],
    ["business_model", "Business Model"],
    ["market_cap", "Market Capitalization"],
    ["segment_exposure", "Segment Exposure"],
    ["geographic_exposure", "Geographic Exposure"],
    ["leadership_governance", "Leadership & Governance"],
    ["major_clients", "Major Clients"],
    ["major_partnerships", "Major Partnerships"],
    ["recent_strategic_actions", "Recent Strategic Actions"],
    ["brand_value_drivers", "Brand Value Drivers"],
    ["rnd_intensity", "R&D Intensity"],
    ["negatives_risks", "Risks & Challenges"]
  ];

  sections.forEach(([key, title]) => {
    if (report[key]) {
      writeSubheading(title);
      writeParagraph(report[key]);
	  cursorY += 5;
    }
  });

  if (report.created_at || report.updated_at) {
    writeSubheading("Metadata");
    if (report.created_at) writeParagraph("Created: " + new Date(report.created_at).toLocaleString());
    if (report.updated_at) writeParagraph("Updated: " + new Date(report.updated_at).toLocaleString());
  }

  pdf.save(`${report.ticker || "report"}.pdf`);
}

