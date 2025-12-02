"use client";

import html2canvas from "html2canvas";
import jsPDF from "jspdf";

export async function downloadCompanyReportPdf() {
  const element = document.getElementById("company-report-pdf");
  if (!element) {
    console.error("PDF element not found");
    return;
  }

  // Force Tailwind color variables to RGB so html2canvas does not encounter LAB/OKLCH formats
  const styleOverride = document.createElement("style");
  styleOverride.id = "pdf-export-override";
  styleOverride.textContent = `
    :root, .dark, * {
      --background: rgb(255, 255, 255) !important;
      --foreground: rgb(37, 37, 37) !important;
      --card: rgb(255, 255, 255) !important;
      --card-foreground: rgb(37, 37, 37) !important;
      --popover: rgb(255, 255, 255) !important;
      --popover-foreground: rgb(37, 37, 37) !important;
      --primary: rgb(37, 37, 37) !important;
      --primary-foreground: rgb(255, 255, 255) !important;
      --secondary: rgb(247, 247, 247) !important;
      --secondary-foreground: rgb(37, 37, 37) !important;
      --muted: rgb(247, 247, 247) !important;
      --muted-foreground: rgb(142, 142, 142) !important;
      --accent: rgb(247, 247, 247) !important;
      --accent-foreground: rgb(37, 37, 37) !important;
      --destructive: rgb(220, 38, 38) !important;
      --border: rgb(235, 235, 235) !important;
      --input: rgb(235, 235, 235) !important;
      --ring: rgb(180, 180, 180) !important;
      --chart-1: rgb(234, 179, 8) !important;
      --chart-2: rgb(34, 197, 94) !important;
      --chart-3: rgb(59, 130, 246) !important;
      --chart-4: rgb(168, 85, 247) !important;
      --chart-5: rgb(236, 72, 153) !important;
    }
  `;
  document.head.insertBefore(styleOverride, document.head.firstChild);

  try {
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "visible";

    // Wait for repaint
    await new Promise((resolve) => setTimeout(resolve, 50));

    // Capture DOM → Canvas
    const canvas = await html2canvas(element, {
      scale: 2,
      useCORS: true,
      allowTaint: true,
      backgroundColor: "#ffffff",
      scrollY: -window.scrollY,
      windowWidth: element.scrollWidth,
      windowHeight: element.scrollHeight,
      onclone: (clonedDoc) => {
        // Remove all stylesheets from cloned document to prevent lab/oklch parsing
        const styleSheets = Array.from(clonedDoc.styleSheets);
        styleSheets.forEach((sheet) => {
          try {
            if (sheet.ownerNode) {
              sheet.ownerNode.remove();
            }
          } catch {}
        });

        // Remove all <style> and <link> tags that might contain problematic colors
        const styles = clonedDoc.querySelectorAll("style, link[rel='stylesheet']");
        styles.forEach((style) => style.remove());

        // Add our RGB-only override to the cloned document
        const safeStyle = clonedDoc.createElement("style");
        safeStyle.textContent = `
          :root, .dark, * {
            --background: rgb(255, 255, 255) !important;
            --foreground: rgb(37, 37, 37) !important;
            --card: rgb(255, 255, 255) !important;
            --card-foreground: rgb(37, 37, 37) !important;
            --popover: rgb(255, 255, 255) !important;
            --popover-foreground: rgb(37, 37, 37) !important;
            --primary: rgb(37, 37, 37) !important;
            --primary-foreground: rgb(255, 255, 255) !important;
            --secondary: rgb(247, 247, 247) !important;
            --secondary-foreground: rgb(37, 37, 37) !important;
            --muted: rgb(247, 247, 247) !important;
            --muted-foreground: rgb(142, 142, 142) !important;
            --accent: rgb(247, 247, 247) !important;
            --accent-foreground: rgb(37, 37, 37) !important;
            --destructive: rgb(220, 38, 38) !important;
            --border: rgb(235, 235, 235) !important;
            --input: rgb(235, 235, 235) !important;
            --ring: rgb(180, 180, 180) !important;
            --chart-1: rgb(234, 179, 8) !important;
            --chart-2: rgb(34, 197, 94) !important;
            --chart-3: rgb(59, 130, 246) !important;
            --chart-4: rgb(168, 85, 247) !important;
            --chart-5: rgb(236, 72, 153) !important;
          }
          * {
            color: rgb(37, 37, 37) !important;
            background-color: rgb(255, 255, 255) !important;
            border-color: rgb(235, 235, 235) !important;
          }
        `;
        clonedDoc.head.appendChild(safeStyle);
      },
    });

    // Get all text elements to find safe break points
    // We'll use the element's scroll positions which match the canvas better
    const textElements: Array<{ top: number; bottom: number; isSection: boolean; priority: number }> = [];
    
    // Get all sections, headings, and paragraphs
    const allElements = element.querySelectorAll("section, h2, h3, p, div[class*='space-y']");
    
    allElements.forEach((el) => {
      const htmlEl = el as HTMLElement;
      const rect = htmlEl.getBoundingClientRect();
      const containerRect = element.getBoundingClientRect();
      
      // Calculate position relative to container
      const relativeTop = rect.top - containerRect.top;
      const relativeBottom = rect.bottom - containerRect.top;
      
      // Scale to canvas coordinates
      const scaleY = canvas.height / containerRect.height;
      const top = relativeTop * scaleY;
      const bottom = relativeBottom * scaleY;
      
      // Determine priority: sections and h2 are highest priority (best break points)
      let priority = 3;
      let isSection = false;
      
      if (el.tagName === "SECTION") {
        priority = 1;
        isSection = true;
      } else if (el.tagName === "H2") {
        priority = 2;
        isSection = true;
      } else if (el.tagName === "H3") {
        priority = 2.5;
      } else if (el.tagName === "P") {
        priority = 3;
      }
      
      // Only add if element is visible and has content
      if (bottom > top && top >= 0 && bottom <= canvas.height) {
        textElements.push({
          top: Math.max(0, top),
          bottom: Math.min(canvas.height, bottom),
          isSection,
          priority,
        });
      }
    });

    // Sort by top position and priority
    textElements.sort((a, b) => {
      if (Math.abs(a.top - b.top) < 5) {
        return a.priority - b.priority; // If close, prefer higher priority
      }
      return a.top - b.top;
    });

    // Convert to image
    const pdf = new jsPDF("p", "mm", "a4");

    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();
    
    // Add margins (50px ≈ 13.2mm)
    const margin = 13.2;
    const contentWidth = pageWidth - (margin * 2);
    const contentHeight = pageHeight - (margin * 2);
    
    // Calculate image dimensions to fit content width
    const imgWidth = contentWidth;
    const imgHeight = (canvas.height * contentWidth) / canvas.width;

    // Calculate how many pixels in canvas correspond to one mm in PDF
    const pixelsPerMm = canvas.width / imgWidth;
    
    // Calculate how many pixels fit in one page (content height)
    const pixelsPerPage = contentHeight * pixelsPerMm;

    let sourceY = 0; // Source Y position in canvas (pixels)
    let pageNumber = 0;

    while (sourceY < canvas.height) {
      if (pageNumber > 0) {
        pdf.addPage();
      }

      // Calculate how many pixels we can fit on this page
      const remainingPixels = canvas.height - sourceY;
      let pixelsThisPage = Math.min(remainingPixels, pixelsPerPage);
      
      // Find the next break point (end of current page)
      const pageEndY = sourceY + pixelsThisPage;
      const minPageHeight = pixelsPerPage * 0.2; // Minimum 20% of page height
      
      // Find elements that would be cut by this page break
      const intersectingElements = textElements.filter(
        (el) => el.top < pageEndY && el.bottom > pageEndY && el.top >= sourceY
      );
      
      if (intersectingElements.length > 0) {
        // Sort by priority (lower number = better break point)
        intersectingElements.sort((a, b) => a.priority - b.priority);
        
        const bestBreak = intersectingElements[0];
        const buffer = 15; // 15 pixels buffer to avoid cutting text
        
        // Try to break before the element
        const breakBefore = bestBreak.top - sourceY - buffer;
        
        if (breakBefore >= minPageHeight) {
          // Good break point before element
          pixelsThisPage = breakBefore;
        } else {
          // Can't break before, try after the element
          const breakAfter = bestBreak.bottom - sourceY + buffer;
          
          if (breakAfter <= pixelsPerPage && breakAfter <= remainingPixels) {
            // Can fit element on this page, break after it
            pixelsThisPage = breakAfter;
          } else if (breakBefore > 0) {
            // Use the before break even if small (better than cutting)
            pixelsThisPage = Math.max(breakBefore, minPageHeight);
          }
          // Otherwise keep original pixelsThisPage
        }
        
        // Ensure we don't exceed remaining pixels
        pixelsThisPage = Math.min(pixelsThisPage, remainingPixels);
      }
      
      // Calculate the height in mm for this page slice
      const pageContentHeightMm = pixelsThisPage / pixelsPerMm;
      
      // Create a canvas slice for this page
      const pageCanvas = document.createElement("canvas");
      pageCanvas.width = canvas.width;
      pageCanvas.height = Math.ceil(pixelsThisPage);
      const pageCtx = pageCanvas.getContext("2d");
      
      if (pageCtx) {
        // Draw the portion of the image for this page
        pageCtx.drawImage(
          canvas,
          0, sourceY, canvas.width, pixelsThisPage, // source rectangle
          0, 0, canvas.width, pixelsThisPage // destination rectangle
        );
        
        const pageImgData = pageCanvas.toDataURL("image/png", 1.0);
        // Add image with proper margins
        pdf.addImage(pageImgData, "PNG", margin, margin, imgWidth, pageContentHeightMm);
      }

      // Move source position forward
      sourceY += pixelsThisPage;
      pageNumber++;
    }

    pdf.save("company-report.pdf");
    document.body.style.overflow = originalOverflow;
  } finally {
    const override = document.getElementById("pdf-export-override");
    if (override) override.remove();
  }
}
