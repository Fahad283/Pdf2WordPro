import {
  Archive, Combine, Crop, FileImage, FileInput, FileOutput, FileText, Hash, ImagePlus,
  LockKeyhole, LockKeyholeOpen, RotateCw, ScanText, Scissors, Stamp,
} from 'lucide-react';

export const TOOLS = [
  { id: 'pdf-to-word', title: 'PDF to Word', description: 'Turn PDFs into editable Word documents.', detail: 'Rebuild a PDF as a Word document with editable text, tables, and images. Use OCR for scanned pages.', icon: FileText, color: 'blue', accept: '.pdf', action: 'Convert to Word' },
  { id: 'ocr-pdf', title: 'OCR PDF', description: 'Make scanned pages searchable.', detail: 'Add a searchable text layer to scanned PDF pages in the languages you select.', icon: ScanText, color: 'violet', accept: '.pdf', action: 'Run OCR' },
  { id: 'merge-pdf', title: 'Merge PDF', description: 'Combine multiple PDFs into one file.', detail: 'Upload PDFs in the order you want them to appear in one combined document.', icon: Combine, color: 'green', accept: '.pdf', action: 'Merge PDFs', combined: true },
  { id: 'split-pdf', title: 'Split PDF', description: 'Separate a PDF into smaller files.', detail: 'Split individual pages or page ranges into separate PDFs and download them in a ZIP archive.', icon: Scissors, color: 'orange', accept: '.pdf', action: 'Split PDF' },
  { id: 'compress-pdf', title: 'Compress PDF', description: 'Reduce the size of a PDF.', detail: 'Optimize PDF structure or reduce image quality to make a smaller file.', icon: Archive, color: 'violet', accept: '.pdf', action: 'Compress PDF' },
  { id: 'word-to-pdf', title: 'Word to PDF', description: 'Export Word documents as PDFs.', detail: 'Render DOCX files as PDFs you can share, print, or archive.', icon: FileOutput, color: 'blue', accept: '.docx', action: 'Convert to PDF' },
  { id: 'rotate-pdf', title: 'Rotate PDF', description: 'Fix the orientation of PDF pages.', detail: 'Rotate an entire document or select the pages you want to adjust.', icon: RotateCw, color: 'green', accept: '.pdf', action: 'Rotate PDF' },
  { id: 'extract-pages', title: 'Extract PDF pages', description: 'Save selected pages as a new PDF.', detail: 'Choose the pages you want to keep, then download a new PDF with those pages.', icon: FileInput, color: 'orange', accept: '.pdf', action: 'Extract pages' },
  { id: 'delete-pages', title: 'Delete PDF pages', description: 'Remove pages from a PDF.', detail: 'Choose the pages you want to remove and download the remaining document.', icon: Crop, color: 'orange', accept: '.pdf', action: 'Delete pages' },
  { id: 'pdf-to-jpg', title: 'PDF to JPG', description: 'Save PDF pages as JPG images.', detail: 'Render PDF pages as individual JPG images and download them in a ZIP archive.', icon: FileImage, color: 'violet', accept: '.pdf', action: 'Convert to JPG' },
  { id: 'jpg-to-pdf', title: 'JPG to PDF', description: 'Combine JPG images into a PDF.', detail: 'Upload JPG images in the order you want them to appear as pages in the new PDF.', icon: ImagePlus, color: 'green', accept: '.jpg,.jpeg', action: 'Create PDF', combined: true },
  { id: 'watermark-pdf', title: 'Watermark PDF', description: 'Add a text watermark to your pages.', detail: 'Place a text watermark on all pages or selected pages of your PDF.', icon: Stamp, color: 'blue', accept: '.pdf', action: 'Add watermark' },
  { id: 'page-numbers', title: 'Add page numbers', description: 'Number pages in your PDF.', detail: 'Add a page number to each selected page and set the number to start from.', icon: Hash, color: 'violet', accept: '.pdf', action: 'Add page numbers' },
  { id: 'protect-pdf', title: 'Protect PDF', description: 'Encrypt a PDF with a password.', detail: 'Set a password that readers need before they can open your PDF.', icon: LockKeyhole, color: 'green', accept: '.pdf', action: 'Protect PDF' },
  { id: 'unlock-pdf', title: 'Unlock PDF', description: 'Remove a password you already know.', detail: 'Enter the password for a PDF you are authorized to unlock, then download a copy that opens without it.', icon: LockKeyholeOpen, color: 'orange', accept: '.pdf', action: 'Unlock PDF' },
] as const;

export type Tool = (typeof TOOLS)[number];
export type ToolId = Tool['id'];

export function getTool(id: string) {
  return TOOLS.find((tool) => tool.id === id);
}

export function isCombined(tool: Tool) {
  return 'combined' in tool && tool.combined;
}
