import { FileText, ScanLine, WandSparkles } from 'lucide-react';

export function ConversionGraphic() {
  return <div className="conversion-graphic" aria-hidden="true">
    <div className="graphic-grid" />
    <div className="graphic-orbit orbit-one" /><div className="graphic-orbit orbit-two" />
    <div className="document-sheet source-sheet">
      <div className="document-fold" />
      <div className="document-format source-format"><FileText size={16} /> PDF</div>
      <div className="document-lines"><i/><i/><i/><i/></div>
      <div className="document-scan"><ScanLine size={34} strokeWidth={1.4} /></div>
      <div className="document-lines bottom-lines"><i/><i/><i/></div>
    </div>
    <div className="conversion-spark"><WandSparkles size={23} strokeWidth={1.85} /></div>
    <div className="document-sheet output-sheet">
      <div className="document-fold" />
      <div className="document-format output-format"><span>W</span> DOCX</div>
      <div className="document-lines"><i/><i/><i/><i/></div>
      <div className="document-table"><b/><b/><b/><b/><b/><b/><b/><b/><b/></div>
      <div className="document-lines bottom-lines"><i/><i/><i/></div>
    </div>
  </div>;
}
