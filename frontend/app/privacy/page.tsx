import type { Metadata } from 'next';

export const metadata: Metadata = { title: 'Privacy and file retention', description: 'Learn how uploads, documents, and job information are handled.', alternates: { canonical: '/privacy' } };

export default function Page() {
  return <section className="shell section-block text-page">
    <h1>Privacy and file retention</h1>
    <h2>Document storage</h2><p>Uploaded files and converted documents are held in private storage while your job runs and while the results are available to download. Upload and output retention defaults to 60 minutes. The upload area displays the policy configured for this deployment.</p>
    <h2>Access and deletion</h2><p>Only the session or account that submitted a job can access its documents. Use the delete button on an upload or job result to request deletion. Scheduled cleanup removes expired file content.</p>
    <h2>Processing and account records</h2><p>Workers process uploaded content for the tool you select. Administrators can access aggregate metrics, account details, and operational errors. Administrators do not have a document browser in the dashboard.</p>
  </section>;
}
