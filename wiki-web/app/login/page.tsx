'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Form, Input, Button, Alert, Typography, ConfigProvider } from 'antd';
import { LockOutlined, UserOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { getAuthRole, getAuthToken, saveAuthSession } from '@/lib/auth-token';

const { Title, Text } = Typography;

export default function LoginPage() {
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const router = useRouter();

    // If already logged in, redirect to wiki or dashboard
    useEffect(() => {
        const token = getAuthToken();
        if (token) {
            const role = getAuthRole();
            if (role === 'admin' || role === 'editor') {
                router.push('/admin/dashboard');
            } else {
                router.push('/wiki');
            }
        }
    }, [router]);

    const handleSubmit = async (values: { username: string; password: string }) => {
        setLoading(true);
        setError('');

        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(values),
            });

            const data = await res.json();

            if (res.ok && data.access_token) {
                // 说明：登录返回的是数据库用户签发的 JWT，不再使用旧的静态管理员 Token 命名。
                saveAuthSession({
                    token: data.access_token,
                    username: data.username,
                    role: data.role,
                });
                
                if (data.role === 'admin' || data.role === 'editor') {
                    router.push('/admin/dashboard');
                } else {
                    router.push('/wiki');
                }
            } else {
                setError(data.detail || '登录失败，请检查用户名和密码。');
            }
        } catch {
            setError('验证失败，请检查网络连接后重试。');
        } finally {
            setLoading(false);
        }
    };

    return (
        <ConfigProvider
            theme={{
                token: {
                    colorPrimary: '#cc785c',
                    fontFamily: 'Inter, -apple-system, sans-serif',
                    borderRadius: 10,
                },
            }}
        >
            <div style={{
                minHeight: '100vh',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: '#faf9f5',
                padding: 24,
            }}>
                {/* Card */}
                <div style={{
                    width: '100%',
                    maxWidth: 420,
                    background: '#ffffff',
                    borderRadius: 24,
                    padding: '48px 40px',
                    boxShadow: '0 8px 40px rgba(20, 20, 19, 0.08)',
                    border: '1px solid rgba(197, 197, 217, 0.15)',
                }}>
                    {/* Icon */}
                    <div style={{
                        width: 64,
                        height: 64,
                        borderRadius: 18,
                        background: '#cc785c',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        margin: '0 auto 28px',
                        boxShadow: '0 8px 24px rgba(204, 120, 92, 0.24)',
                    }}>
                        <SafetyCertificateOutlined style={{ fontSize: 28, color: '#ffffff' }} />
                    </div>

                    {/* Title */}
                    <div style={{ textAlign: 'center', marginBottom: 32 }}>
                        <Title level={3} style={{
                            fontFamily: 'Manrope, sans-serif',
                            fontWeight: 800,
                            letterSpacing: '-0.03em',
                            color: '#181d1a',
                            margin: '0 0 8px',
                        }}>
                            Wiki 知识库登录
                        </Title>
                        <Text style={{
                            color: '#757688',
                            fontSize: 14,
                            fontFamily: 'Inter, sans-serif',
                        }}>
                            请输入用户名和密码以继续
                        </Text>
                    </div>

                    {/* Form */}
                    <Form
                        layout="vertical"
                        onFinish={handleSubmit}
                        requiredMark={false}
                        initialValues={{ username: 'admin' }}
                    >
                        <Form.Item
                            name="username"
                            label={
                                <span style={{
                                    fontSize: 13,
                                    fontWeight: 600,
                                    color: '#444656',
                                    fontFamily: 'Inter, sans-serif',
                                }}>
                                    用户名
                                </span>
                            }
                            rules={[{ required: true, message: '请输入用户名' }]}
                        >
                            <Input
                                prefix={<UserOutlined style={{ color: '#757688' }} />}
                                placeholder="输入用户名..."
                                size="large"
                                style={{
                                    borderRadius: 12,
                                    fontFamily: 'Inter, sans-serif',
                                    fontSize: 14,
                                }}
                            />
                        </Form.Item>

                        <Form.Item
                            name="password"
                            label={
                                <span style={{
                                    fontSize: 13,
                                    fontWeight: 600,
                                    color: '#444656',
                                    fontFamily: 'Inter, sans-serif',
                                }}>
                                    密码
                                </span>
                            }
                            rules={[{ required: true, message: '请输入密码' }]}
                        >
                            <Input.Password
                                prefix={<LockOutlined style={{ color: '#757688' }} />}
                                placeholder="输入密码..."
                                size="large"
                                style={{
                                    borderRadius: 12,
                                    fontFamily: 'Inter, sans-serif',
                                    fontSize: 14,
                                }}
                            />
                        </Form.Item>

                        {error && (
                            <Form.Item>
                                <Alert
                                    message={error}
                                    type="error"
                                    showIcon
                                    style={{ borderRadius: 10 }}
                                />
                            </Form.Item>
                        )}

                        <Form.Item style={{ marginBottom: 0 }}>
                            <Button
                                type="primary"
                                htmlType="submit"
                                loading={loading}
                                size="large"
                                block
                                style={{
                                    borderRadius: 12,
                                    height: 48,
                                    fontSize: 15,
                                    fontWeight: 700,
                                    fontFamily: 'Manrope, sans-serif',
                                    background: '#cc785c',
                                    border: 'none',
                                    boxShadow: '0 4px 20px rgba(204, 120, 92, 0.24)',
                                }}
                            >
                                {loading ? '验证中...' : '登录'}
                            </Button>
                        </Form.Item>
                    </Form>
                </div>
            </div>
        </ConfigProvider>
    );
}
