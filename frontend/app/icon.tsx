import { ImageResponse } from 'next/og';

export const size = { width: 64, height: 64 };
export const contentType = 'image/png';

export default function Icon() {
  return new ImageResponse(<div style={{ width: 64, height: 64, display: 'flex', justifyContent: 'center', alignItems: 'center', borderRadius: 17, background: '#2458e8' }}>
    <div style={{ width: 28, height: 35, display: 'flex', flexDirection: 'column', gap: 4, justifyContent: 'center', alignItems: 'center', borderRadius: 5, border: '3px solid white' }}>
      <div style={{ width: 12, height: 3, borderRadius: 2, background: 'white' }} /><div style={{ width: 12, height: 3, borderRadius: 2, background: 'white' }} />
    </div>
  </div>, size);
}
