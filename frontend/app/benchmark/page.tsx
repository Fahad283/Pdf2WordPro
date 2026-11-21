import type { Metadata } from 'next';
import { Suspense } from 'react';
import { BenchmarkDashboard } from '@/components/benchmark/dashboard';
import './benchmark.css';

export const metadata: Metadata = {
  title: 'PDF2DOCX-BENCH',
  description: 'Versioned document conversion benchmarks and diagnostics.',
  robots: { index: false, follow: false },
};

export default function BenchmarkPage() {
  return <Suspense fallback={<div className="bench-shell bench-loading" role="status">Loading benchmarks</div>}>
    <BenchmarkDashboard />
  </Suspense>;
}
