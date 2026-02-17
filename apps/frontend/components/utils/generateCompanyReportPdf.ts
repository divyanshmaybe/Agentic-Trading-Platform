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

	const currencyMap: Record<string, string> = {
		"₹": "INR ",
		"$": "USD ",
		"€": "EUR ",
		"£": "GBP ",
		"¥": "JPY ",    // could be CNY or JPY but JPY is more common for symbol parsing
		"₩": "KRW ",
		"₽": "RUB ",
		"₺": "TRY ",
		"A$": "AUD ",
		"C$": "CAD ",
		"₫": "VND ",
		"R$": "BRL ",
		"₪": "ILS ",
		"₱": "PHP ",
		"₣": "CHF ",
		"HK$": "HKD ",
		"S$": "SGD ",
		"AED": "AED ", // some currencies are text only
	};

	const clean = (str: string): string => {
		if (!str) return str;

		let out = str
			.normalize("NFKC")
			.replace(/[\u200B-\u200D\u2060\uFEFF]/g, "")
			.replace(/[\u00A0]/g, " ")
			.replace(/\s+/g, " ");

		// Replace currency symbols
		for (const [symbol, code] of Object.entries(currencyMap)) {
			const escaped = symbol.replace(/[-\/\\^$*+?.()|[\]{}]/g, "\\$&");
			out = out.replace(new RegExp(escaped, "g"), code);
		}

		return out.trim();
	};

	const ensureSpace = (needed: number) => {
		if (cursorY + needed > pageHeight - margin) {
			pdf.addPage();
			cursorY = margin;
		}
	};

  const writeHeading = (text: string, size = 18) => {
    text = clean(text);
    pdf.setFont("times", "bold");
    pdf.setFontSize(size);

    const lineHeight = size * 0.55;
    const lines: string[] = pdf.splitTextToSize(text, contentWidth);

    ensureSpace(lines.length * lineHeight);
    lines.forEach((line: string) => {
      pdf.text(line, margin, cursorY);
      cursorY += lineHeight;
    });
    cursorY += 4;
  };

	const writeSubheading = (text: string) => {
		text = clean(text);
		pdf.setFont("times", "bold");
		pdf.setFontSize(15);

		const lines: string[] = pdf.splitTextToSize(text, contentWidth);
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
		pdf.setFont("helvetica", "italic");
		pdf.setFontSize(12);

		const lines: string[] = pdf.splitTextToSize(text, contentWidth);
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

