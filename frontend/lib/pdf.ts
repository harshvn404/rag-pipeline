export function selectPdfFiles(incoming: FileList | File[] | null): {
  pdfs: File[];
  hasInvalid: boolean;
} {
  if (!incoming) return { pdfs: [], hasInvalid: false };

  const candidates = Array.from(incoming);
  const pdfs = candidates.filter(
    (file) => file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"),
  );

  return { pdfs, hasInvalid: pdfs.length !== candidates.length };
}
