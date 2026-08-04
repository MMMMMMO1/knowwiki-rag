export default function AdminLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <div style={{ minHeight: '100vh', background: '#faf9f5' }}>
            {children}
        </div>
    );
}
