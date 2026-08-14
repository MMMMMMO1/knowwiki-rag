'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import {
    Layout, Menu, Button, Typography, Card, ConfigProvider, Spin, Table,
    Modal, Form, Input, Select, Tag, Space, Row, Col, Statistic,
    message, Drawer, List, Avatar, Tooltip
} from 'antd';
import {
    LogoutOutlined, FolderOpenOutlined, ArrowLeftOutlined,
    DashboardOutlined, SyncOutlined, UserOutlined, MessageOutlined,
    PlusOutlined, DeleteOutlined, EditOutlined, ReloadOutlined
} from '@ant-design/icons';
import { AdminFileManager } from '@/components/admin/AdminFileManager';
import Link from 'next/link';
import { clearAuthSession, getAuthRole, getAuthToken, installAuthExpirationHandler } from '@/lib/auth-token';

const { Header, Content, Sider } = Layout;
const { Title, Text } = Typography;

interface UserItem {
    id: number;
    username: string;
    role: string;
    is_active: boolean;
}

interface ChatSession {
    session_id: string;
    username: string;
    user_id: number;
    message_count: number;
    latest_message_time: string;
}

interface ChatMessage {
    id: number;
    role: 'user' | 'assistant';
    content: string;
    created_at: string;
}

interface SyncRecord {
    id: number;
    doc_id: string;
    file_id: number | null;
    title: string;
    full_path: string | null;
    storage_key: string | null;
    status: string;
    retry_count: number;
    chunk_count: number;
    error_message: string | null;
    content_hash: string | null;
    queued_at: string | null;
    processing_started_at: string | null;
    completed_at: string | null;
    failed_at: string | null;
    created_at: string;
    updated_at: string;
}

interface DashboardStats {
    total_folders: number;
    total_files: number;
    total_users: number;
    total_conversations: number;
    failed_syncs: number;
}

type UserFormValues = {
    username: string;
    password?: string;
    role: UserItem['role'];
    is_active: boolean;
};

export default function AdminDashboard() {
    const [token, setToken] = useState<string | null>(() => (
        typeof window === 'undefined' ? null : getAuthToken()
    ));
    const [activeTab, setActiveTab] = useState('overview');
    const [refreshKey, setRefreshKey] = useState(0);
    const router = useRouter();

    // Stats state
    const [stats, setStats] = useState<DashboardStats | null>(null);
    const [statsLoading, setStatsLoading] = useState(false);

    // Users state
    const [users, setUsers] = useState<UserItem[]>([]);
    const [usersLoading, setUsersLoading] = useState(false);
    const [userModalOpen, setUserModalOpen] = useState(false);
    const [editingUser, setEditingUser] = useState<UserItem | null>(null);
    const [userForm] = Form.useForm();

    // Chat sessions audit state
    const [sessions, setSessions] = useState<ChatSession[]>([]);
    const [sessionsLoading, setSessionsLoading] = useState(false);
    const [selectedSession, setSelectedSession] = useState<ChatSession | null>(null);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [messagesLoading, setMessagesLoading] = useState(false);
    const [chatDrawerOpen, setChatDrawerOpen] = useState(false);

    // Sync Center state
    const [syncHistory, setSyncHistory] = useState<SyncRecord[]>([]);
    const [syncHistoryLoading, setSyncHistoryLoading] = useState(false);
    const [syncRetrying, setSyncRetrying] = useState(false);
    const [rebuilding, setRebuilding] = useState(false);

    // Auth check
    useEffect(() => {
        installAuthExpirationHandler();
    }, []);

    useEffect(() => {
        if (!token) {
            router.push('/login');
        } else {
            const role = getAuthRole();
            if (role !== 'admin' && role !== 'editor') {
                router.push('/wiki');
            }
        }
    }, [router, token]);

    const handleLogout = () => {
        clearAuthSession();
        setToken(null);
        router.push('/login');
    };

    /* ─── Fetch Data Helpers ─── */

    const fetchStats = useCallback(async () => {
        if (!token) return;
        setStatsLoading(true);
        try {
            const res = await fetch('/api/admin/stats', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.ok) {
                const data = await res.json();
                setStats(data);
            }
        } catch (e) {
            console.error('Fetch stats failed', e);
        } finally {
            setStatsLoading(false);
        }
    }, [token]);

    const fetchUsers = useCallback(async () => {
        if (!token) return;
        setUsersLoading(true);
        try {
            const res = await fetch('/api/admin/users', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.ok) {
                const data = await res.json();
                setUsers(data);
            }
        } catch (e) {
            console.error('Fetch users failed', e);
        } finally {
            setUsersLoading(false);
        }
    }, [token]);

    const fetchSyncHistory = useCallback(async () => {
        if (!token) return;
        setSyncHistoryLoading(true);
        try {
            const res = await fetch('/api/admin/sync-history?limit=30', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.ok) {
                const data = await res.json();
                setSyncHistory(data);
            }
        } catch (e) {
            console.error('Fetch sync history failed', e);
        } finally {
            setSyncHistoryLoading(false);
        }
    }, [token]);

    const fetchChatSessions = useCallback(async () => {
        if (!token) return;
        setSessionsLoading(true);
        try {
            const res = await fetch('/api/admin/chat-sessions', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.ok) {
                const data = await res.json();
                setSessions(data);
            }
        } catch (e) {
            console.error('Fetch chat sessions failed', e);
        } finally {
            setSessionsLoading(false);
        }
    }, [token]);

    const fetchSessionMessages = async (sessionId: string) => {
        if (!token) return;
        setMessagesLoading(true);
        try {
            const res = await fetch(`/api/admin/chat-sessions/${sessionId}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.ok) {
                const data = await res.json();
                setMessages(data);
            }
        } catch (e) {
            console.error('Fetch session messages failed', e);
        } finally {
            setMessagesLoading(false);
        }
    };

    // Load active tab data
    useEffect(() => {
        if (activeTab === 'overview') {
            fetchStats();
        } else if (activeTab === 'users') {
            fetchUsers();
        } else if (activeTab === 'sync') {
            fetchSyncHistory();
        } else if (activeTab === 'chat-audit') {
            fetchChatSessions();
        }
    }, [activeTab, fetchStats, fetchUsers, fetchSyncHistory, fetchChatSessions]);

    // Overview statistics load
    useEffect(() => {
        fetchStats();
    }, [fetchStats]);

    /* ─── User Management Actions ─── */

    const openCreateUserModal = () => {
        setEditingUser(null);
        userForm.resetFields();
        setUserModalOpen(true);
    };

    const openEditUserModal = (user: UserItem) => {
        setEditingUser(user);
        userForm.setFieldsValue({
            username: user.username,
            role: user.role,
            is_active: user.is_active,
            password: '' // Keep empty to avoid displaying hash
        });
        setUserModalOpen(true);
    };

    const handleUserFormSubmit = async (values: UserFormValues) => {
        if (!token) return;
        try {
            if (editingUser) {
                // Update User
                const res = await fetch(`/api/admin/users/${editingUser.id}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`
                    },
                    body: JSON.stringify({
                        role: values.role,
                        is_active: values.is_active,
                        password: values.password || undefined
                    })
                });
                if (res.ok) {
                    message.success('用户更新成功');
                    setUserModalOpen(false);
                    fetchUsers();
                } else {
                    const data = await res.json();
                    message.error(data.detail || '更新用户失败');
                }
            } else {
                // Create User
                const res = await fetch('/api/admin/users', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`
                    },
                    body: JSON.stringify(values)
                });
                if (res.ok) {
                    message.success('用户创建成功');
                    setUserModalOpen(false);
                    fetchUsers();
                } else {
                    const data = await res.json();
                    message.error(data.detail || '创建用户失败');
                }
            }
        } catch {
            message.error('操作失败，请检查网络');
        }
    };

    const handleDeleteUser = (user: UserItem) => {
        Modal.confirm({
            title: '确认删除用户',
            content: `您确定要删除账户 "${user.username}" 吗？此操作将永久移除该用户及其关联的全部数据。`,
            okText: '删除',
            cancelText: '取消',
            okButtonProps: { danger: true },
            onOk: async () => {
                if (!token) return;
                try {
                    const res = await fetch(`/api/admin/users/${user.id}`, {
                        method: 'DELETE',
                        headers: { 'Authorization': `Bearer ${token}` }
                    });
                    if (res.ok) {
                        message.success('用户已被成功删除');
                        fetchUsers();
                    } else {
                        const data = await res.json();
                        message.error(data.detail || '删除用户失败');
                    }
                } catch {
                    message.error('删除操作失败，请重试');
                }
            }
        });
    };

    /* ─── Sync Center Actions ─── */

    const triggerManualSync = async () => {
        if (!token) return;
        setSyncRetrying(true);
        try {
            const res = await fetch('/api/admin/knowledge/sync', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.ok) {
                const data = await res.json();
                message.success(data.message || '已补投待处理/失败任务');
                fetchSyncHistory();
                fetchStats();
            } else {
                const data = await res.json();
                message.error(data.message || '补投失败');
            }
        } catch {
            message.error('连接失败');
        } finally {
            setSyncRetrying(false);
        }
    };

    const triggerRebuild = async () => {
        if (!token) return;
        setRebuilding(true);
        try {
            const res = await fetch('/api/admin/knowledge/rebuild', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.ok) {
                const data = await res.json();
                message.success(data.message || '已触发全量补齐');
                fetchSyncHistory();
                fetchStats();
            } else {
                const data = await res.json();
                message.error(data.message || '全量补齐失败');
            }
        } catch {
            message.error('连接失败');
        } finally {
            setRebuilding(false);
        }
    };

    /* ─── Chat Audit Actions ─── */

    const handleInspectSession = (session: ChatSession) => {
        setSelectedSession(session);
        setMessages([]);
        setChatDrawerOpen(true);
        fetchSessionMessages(session.session_id);
    };

    /* ─── Render Panels ─── */

    const renderOverview = () => {
        if (statsLoading && !stats) {
            return <div style={{ padding: 48, textAlign: 'center' }}><Spin size="large" /></div>;
        }

        const metrics = [
            { title: '文档文件数', value: stats?.total_files ?? 0, icon: <FolderOpenOutlined style={{ color: '#1677ff' }} /> },
            { title: '目录文件夹', value: stats?.total_folders ?? 0, icon: <FolderOpenOutlined style={{ color: '#faad14' }} /> },
            { title: '注册用户账户', value: stats?.total_users ?? 0, icon: <UserOutlined style={{ color: '#52c41a' }} /> },
            { title: '对话会话数', value: stats?.total_conversations ?? 0, icon: <MessageOutlined style={{ color: '#eb2f96' }} /> },
        ];

        return (
            <Space direction="vertical" size="large" style={{ width: '100%' }}>
                {/* Metrics */}
                <Row gutter={[16, 16]}>
                    {metrics.map((m, idx) => (
                        <Col xs={24} sm={12} md={6} key={idx}>
                            <Card variant="borderless" style={{ boxShadow: '0 4px 12px rgba(0,0,0,0.03)', borderRadius: 16 }}>
                                <Statistic
                                    title={<span style={{ fontFamily: 'Inter', fontSize: 13, color: '#757688' }}>{m.title}</span>}
                                    value={m.value}
                                    prefix={m.icon}
                                    valueStyle={{ fontFamily: 'Manrope', fontWeight: 800, color: '#181d1a' }}
                                />
                            </Card>
                        </Col>
                    ))}
                </Row>

                {/* Info Card */}
                <Card variant="borderless" style={{ boxShadow: '0 4px 12px rgba(0,0,0,0.03)', borderRadius: 16 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
                        <Title level={4} style={{ fontFamily: 'Manrope', margin: 0, letterSpacing: '-0.02em' }}>
                            系统状态与同步状态
                        </Title>
                        <Button type="primary" onClick={fetchStats} icon={<ReloadOutlined />} size="small" style={{ background: '#cc785c', border: 'none' }} />
                    </div>

                    <Row gutter={24}>
                        <Col xs={24} md={12}>
                            <div style={{ background: '#faf9f5', padding: 24, borderRadius: 12, height: '100%' }}>
                                <Title level={5} style={{ fontFamily: 'Manrope', color: '#cc785c' }}>知识库同步健康</Title>
                                <Space direction="vertical" style={{ width: '100%', marginTop: 12 }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                        <Text>异常同步失败任务：</Text>
                                        <Tag color={stats?.failed_syncs ? 'red' : 'green'} style={{ borderRadius: 6, fontWeight: 'bold' }}>
                                            {stats?.failed_syncs ? `${stats.failed_syncs} 个任务失败` : '无失败任务'}
                                        </Tag>
                                    </div>
                                    <Text style={{ fontSize: 12, color: '#757688' }}>
                                        提示：如果存在失败任务，您可导航至「同步中心」查看详细错误日志，并手动重新排队同步该文件。
                                    </Text>
                                </Space>
                            </div>
                        </Col>
                        <Col xs={24} md={12}>
                            <div style={{ background: '#faf9f5', padding: 24, borderRadius: 12, height: '100%' }}>
                                <Title level={5} style={{ fontFamily: 'Manrope', color: '#cc785c' }}>快捷管理</Title>
                                <Space wrap style={{ marginTop: 12 }}>
                                    <Button onClick={() => setActiveTab('files')} icon={<FolderOpenOutlined />}>进入文件管理</Button>
                                    <Button onClick={() => setActiveTab('users')} icon={<UserOutlined />}>管理用户账号</Button>
                                    <Button onClick={() => setActiveTab('chat-audit')} icon={<MessageOutlined />}>审计对话日志</Button>
                                </Space>
                            </div>
                        </Col>
                    </Row>
                </Card>
            </Space>
        );
    };

    const renderUsers = () => {
        const columns = [
            {
                title: '用户名',
                dataIndex: 'username',
                key: 'username',
                render: (text: string) => <Text strong style={{ fontFamily: 'Inter' }}>{text}</Text>
            },
            {
                title: '权限角色',
                dataIndex: 'role',
                key: 'role',
                render: (role: string) => {
                    const color = role === 'admin' ? 'red' : role === 'editor' ? 'orange' : 'blue';
                    const text = role === 'admin' ? '管理员' : role === 'editor' ? '编辑者' : '阅读者';
                    return <Tag color={color} style={{ borderRadius: 6 }}>{text}</Tag>;
                }
            },
            {
                title: '账号状态',
                dataIndex: 'is_active',
                key: 'is_active',
                render: (active: boolean) => (
                    <Tag color={active ? 'success' : 'default'} style={{ borderRadius: 6 }}>
                        {active ? '已启用' : '已禁用'}
                    </Tag>
                )
            },
            {
                title: '操作',
                key: 'action',
                render: (_: unknown, record: UserItem) => (
                    <Space size="middle">
                        <Button type="text" icon={<EditOutlined />} onClick={() => openEditUserModal(record)}>编辑</Button>
                        <Button type="text" danger icon={<DeleteOutlined />} onClick={() => handleDeleteUser(record)} disabled={record.id === 0}>删除</Button>
                    </Space>
                )
            }
        ];

        return (
            <Card variant="borderless" style={{ boxShadow: '0 4px 12px rgba(0,0,0,0.03)', borderRadius: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
                    <Title level={4} style={{ fontFamily: 'Manrope', margin: 0, letterSpacing: '-0.02em' }}>
                        用户账号管理
                    </Title>
                    <Space>
                        <Button type="primary" onClick={openCreateUserModal} icon={<PlusOutlined />} style={{ background: '#cc785c', border: 'none', borderRadius: 8 }}>
                            创建账户
                        </Button>
                        <Button onClick={fetchUsers} icon={<ReloadOutlined />} style={{ borderRadius: 8 }} />
                    </Space>
                </div>

                <Table
                    columns={columns}
                    dataSource={users}
                    rowKey="id"
                    loading={usersLoading}
                    pagination={{ pageSize: 10 }}
                    style={{ fontFamily: 'Inter' }}
                />
            </Card>
        );
    };

    const renderSync = () => {
        const columns = [
            {
                title: '文件标题',
                dataIndex: 'title',
                key: 'title',
                render: (text: string, r: SyncRecord) => (
                    <Space direction="vertical" size={2}>
                        <Text strong style={{ fontSize: 13 }}>{text}</Text>
                        <Text type="secondary" style={{ fontSize: 11, fontFamily: 'monospace' }}>
                            {r.full_path || r.storage_key || '—'}
                        </Text>
                    </Space>
                )
            },
            {
                title: '同步状态',
                dataIndex: 'status',
                key: 'status',
                render: (status: string) => {
                    let color = 'default';
                    let text = status;
                    if (status === 'completed') { color = 'green'; text = '已完成'; }
                    else if (status === 'failed') { color = 'red'; text = '失败'; }
                    else if (status === 'pending') { color = 'blue'; text = '排队中'; }
                    else if (status === 'processing') { color = 'orange'; text = '处理中'; }
                    else if (status === 'skipped') { color = 'default'; text = '已跳过'; }
                    return <Tag color={color}>{text}</Tag>;
                }
            },
            {
                title: '重试次数',
                dataIndex: 'retry_count',
                key: 'retry_count',
                render: (count: number) => count > 0 ? <Tag color="gold">{count}</Tag> : <Text type="secondary">0</Text>
            },
            {
                title: '分块数',
                dataIndex: 'chunk_count',
                key: 'chunk_count',
                render: (count: number) => count > 0 ? count : '—'
            },
            {
                title: '错误详情',
                dataIndex: 'error_message',
                key: 'error_message',
                width: 250,
                render: (err: string | null) => err ? (
                    <Tooltip title={err}>
                        <Text type="danger" ellipsis style={{ maxWidth: 240, fontSize: 11 }}>{err}</Text>
                    </Tooltip>
                ) : <Text type="secondary">—</Text>
            },
            {
                title: '入队时间',
                dataIndex: 'queued_at',
                key: 'queued_at',
                render: (t: string | null) => t ? new Date(t).toLocaleString('zh-CN') : '—'
            },
            {
                title: '更新时间',
                dataIndex: 'updated_at',
                key: 'updated_at',
                render: (t: string) => new Date(t).toLocaleString('zh-CN')
            }
        ];

        return (
            <Card variant="borderless" style={{ boxShadow: '0 4px 12px rgba(0,0,0,0.03)', borderRadius: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
                    <Title level={4} style={{ fontFamily: 'Manrope', margin: 0, letterSpacing: '-0.02em' }}>
                        知识库同步任务中心
                    </Title>
                    <Space>
                        <Button type="primary" onClick={triggerManualSync} loading={syncRetrying} icon={<SyncOutlined spin={syncRetrying} />} style={{ background: '#cc785c', border: 'none', borderRadius: 8 }}>
                            补投待处理/失败任务
                        </Button>
                        <Button onClick={triggerRebuild} loading={rebuilding} icon={<SyncOutlined spin={rebuilding} />} style={{ borderRadius: 8 }}>
                            全量补齐
                        </Button>
                        <Button onClick={fetchSyncHistory} icon={<ReloadOutlined />} style={{ borderRadius: 8 }} />
                    </Space>
                </div>

                <Table
                    columns={columns}
                    dataSource={syncHistory}
                    rowKey="id"
                    loading={syncHistoryLoading}
                    pagination={{ pageSize: 15 }}
                    style={{ fontFamily: 'Inter' }}
                />
            </Card>
        );
    };

    const renderChatAudit = () => {
        const columns = [
            {
                title: '会话用户',
                dataIndex: 'username',
                key: 'username',
                render: (text: string) => <Text strong><UserOutlined style={{ marginRight: 6 }} />{text}</Text>
            },
            {
                title: '会话消息量',
                dataIndex: 'message_count',
                key: 'message_count',
                render: (cnt: number) => <Tag color="blue" style={{ borderRadius: 6 }}>{cnt} 条记录</Tag>
            },
            {
                title: '最新对话时间',
                dataIndex: 'latest_message_time',
                key: 'latest_message_time',
                render: (t: string) => new Date(t).toLocaleString('zh-CN')
            },
            {
                title: '会话ID',
                dataIndex: 'session_id',
                key: 'session_id',
                render: (id: string) => <Text copyable style={{ fontSize: 11, fontFamily: 'monospace' }}>{id}</Text>
            },
            {
                title: '操作',
                key: 'action',
                render: (_: unknown, record: ChatSession) => (
                    <Button type="text" icon={<MessageOutlined />} onClick={() => handleInspectSession(record)}>
                        审计对话
                    </Button>
                )
            }
        ];

        return (
            <Card variant="borderless" style={{ boxShadow: '0 4px 12px rgba(0,0,0,0.03)', borderRadius: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
                    <Title level={4} style={{ fontFamily: 'Manrope', margin: 0, letterSpacing: '-0.02em' }}>
                        用户对话会话审计
                    </Title>
                    <Button onClick={fetchChatSessions} icon={<ReloadOutlined />} style={{ borderRadius: 8 }} />
                </div>

                <Table
                    columns={columns}
                    dataSource={sessions}
                    rowKey="session_id"
                    loading={sessionsLoading}
                    pagination={{ pageSize: 10 }}
                    style={{ fontFamily: 'Inter' }}
                />
            </Card>
        );
    };

    if (!token) {
        return (
            <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Spin size="large" />
            </div>
        );
    }

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
            <Layout style={{ minHeight: '100vh', background: '#faf9f5' }}>
                {/* Header */}
                <Header style={{
                    background: '#ffffff',
                    borderBottom: 'none',
                    padding: '0 40px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    boxShadow: '0 1px 8px rgba(0,0,0,0.04)',
                    position: 'sticky',
                    top: 0,
                    zIndex: 100,
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
                        <Link href="/wiki">
                            <Button
                                type="text"
                                icon={<ArrowLeftOutlined />}
                                style={{ color: '#757688', fontFamily: 'Inter, sans-serif' }}
                            >
                                返回文档
                            </Button>
                        </Link>
                        <div style={{ width: 1, height: 20, background: 'rgba(197,197,217,0.3)', margin: '0 8px' }} />
                        <span style={{
                            fontSize: 18,
                            fontWeight: 800,
                            fontFamily: 'Manrope, sans-serif',
                            color: '#cc785c',
                            letterSpacing: '-0.03em',
                        }}>
                            管理员后台
                        </span>
                    </div>

                    <Button
                        type="text"
                        icon={<LogoutOutlined />}
                        onClick={handleLogout}
                        danger
                        style={{ fontFamily: 'Inter, sans-serif' }}
                    >
                        退出登录
                    </Button>
                </Header>

                <Layout style={{ background: 'transparent' }}>
                    {/* Sider Navigation */}
                    <Sider
                        width={220}
                        style={{
                            background: '#ffffff',
                            borderRight: '1px solid rgba(197, 197, 217, 0.15)',
                            boxShadow: '0 4px 12px rgba(0,0,0,0.01)'
                        }}
                    >
                        <Menu
                            mode="inline"
                            selectedKeys={[activeTab]}
                            onClick={(e) => setActiveTab(e.key)}
                            style={{ borderRight: 'none', paddingTop: 16 }}
                            items={[
                                { key: 'overview', icon: <DashboardOutlined />, label: '系统概览' },
                                { key: 'files', icon: <FolderOpenOutlined />, label: '文件管理' },
                                { key: 'sync', icon: <SyncOutlined />, label: '同步中心' },
                                { key: 'users', icon: <UserOutlined />, label: '用户管理' },
                                { key: 'chat-audit', icon: <MessageOutlined />, label: '聊天审计' },
                            ]}
                        />
                    </Sider>

                    {/* Content */}
                    <Content style={{ padding: '32px 40px', overflowY: 'auto' }}>
                        {activeTab === 'overview' && renderOverview()}
                        
                        {activeTab === 'files' && (
                            <Card variant="borderless" style={{ borderRadius: 20, boxShadow: '0 4px 12px rgba(0,0,0,0.03)' }}>
                                <Title level={4} style={{ fontFamily: 'Manrope, sans-serif', margin: '0 0 20px', letterSpacing: '-0.02em' }}>
                                    <FolderOpenOutlined style={{ marginRight: 10, color: '#cc785c' }} />
                                    目录文件管理
                                </Title>
                                <AdminFileManager key={refreshKey} token={token} onTreeChange={() => setRefreshKey(k => k + 1)} />
                            </Card>
                        )}

                        {activeTab === 'sync' && renderSync()}
                        {activeTab === 'users' && renderUsers()}
                        {activeTab === 'chat-audit' && renderChatAudit()}
                    </Content>
                </Layout>
            </Layout>

            {/* Modal: Create/Edit User */}
            <Modal
                title={editingUser ? '编辑用户账号' : '创建用户账号'}
                open={userModalOpen}
                onCancel={() => setUserModalOpen(false)}
                footer={null}
                style={{ fontFamily: 'Inter' }}
            >
                <Form
                    form={userForm}
                    layout="vertical"
                    onFinish={handleUserFormSubmit}
                    requiredMark={false}
                >
                    <Form.Item
                        name="username"
                        label="用户名"
                        rules={[{ required: true, message: '请输入用户名' }]}
                    >
                        <Input disabled={!!editingUser} placeholder="输入账户登录用户名..." size="large" style={{ borderRadius: 8 }} />
                    </Form.Item>

                    <Form.Item
                        name="password"
                        label={editingUser ? '重置密码 (留空则不修改)' : '密码'}
                        rules={editingUser ? [] : [{ required: true, message: '请输入账户密码' }]}
                    >
                        <Input.Password placeholder="输入账户密码..." size="large" style={{ borderRadius: 8 }} />
                    </Form.Item>

                    <Form.Item
                        name="role"
                        label="权限角色"
                        rules={[{ required: true, message: '请选择权限角色' }]}
                        initialValue="reader"
                    >
                        <Select size="large" style={{ borderRadius: 8 }}>
                            <Select.Option value="reader">阅读者 (只能看文档/聊天)</Select.Option>
                            <Select.Option value="editor">编辑者 (可以写文档/同步，无用户管理权)</Select.Option>
                            <Select.Option value="admin">管理员 (完全权限，包括用户管理与审计)</Select.Option>
                        </Select>
                    </Form.Item>

                    {editingUser && (
                        <Form.Item
                            name="is_active"
                            label="账户启用状态"
                            valuePropName="checked"
                            initialValue={true}
                        >
                            <Select size="large" style={{ borderRadius: 8 }}>
                                <Select.Option value={true}>启用账号</Select.Option>
                                <Select.Option value={false}>禁用账号</Select.Option>
                            </Select>
                        </Form.Item>
                    )}

                    <Form.Item style={{ marginBottom: 0, marginTop: 24, textAlign: 'right' }}>
                        <Space>
                            <Button onClick={() => setUserModalOpen(false)} style={{ borderRadius: 8 }}>取消</Button>
                            <Button type="primary" htmlType="submit" style={{ background: '#cc785c', border: 'none', borderRadius: 8 }}>
                                确认提交
                            </Button>
                        </Space>
                    </Form.Item>
                </Form>
            </Modal>

            {/* Drawer: Inspect Chat logs */}
            <Drawer
                title={
                    <Space direction="vertical" size={2}>
                        <Text strong style={{ fontSize: 16 }}>对话日志审计</Text>
                        {selectedSession && (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                                用户: <strong>{selectedSession.username}</strong> | 会话ID: {selectedSession.session_id.slice(0, 8)}...
                            </Text>
                        )}
                    </Space>
                }
                placement="right"
                width={500}
                onClose={() => setChatDrawerOpen(false)}
                open={chatDrawerOpen}
                style={{ fontFamily: 'Inter' }}
            >
                {messagesLoading ? (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
                        <Spin size="large" />
                    </div>
                ) : messages.length === 0 ? (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#757688' }}>
                        暂无对话数据
                    </div>
                ) : (
                    <List
                        dataSource={messages}
                        renderItem={(msg) => {
                            const isUser = msg.role === 'user';
                            return (
                                <List.Item style={{ borderBottom: 'none', padding: '12px 0' }}>
                                    <div style={{
                                        display: 'flex',
                                        width: '100%',
                                        flexDirection: isUser ? 'row-reverse' : 'row',
                                        alignItems: 'flex-start',
                                        gap: 12
                                    }}>
                                        <Avatar
                                            icon={isUser ? <UserOutlined /> : <SyncOutlined />}
                                            style={{
                                                background: isUser ? '#cc785c' : '#1677ff',
                                                flexShrink: 0
                                            }}
                                        />
                                        <div style={{
                                            maxWidth: '75%',
                                            background: isUser ? '#f0f0f0' : '#e6f7ff',
                                            padding: '12px 16px',
                                            borderRadius: 12,
                                            borderTopLeftRadius: isUser ? 12 : 2,
                                            borderTopRightRadius: isUser ? 2 : 12,
                                            boxShadow: '0 2px 8px rgba(0,0,0,0.03)'
                                        }}>
                                            <div style={{ fontSize: 13, lineHeight: '1.5', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                                {msg.content}
                                            </div>
                                            <div style={{ fontSize: 10, color: '#909090', marginTop: 6, textAlign: isUser ? 'right' : 'left' }}>
                                                {new Date(msg.created_at).toLocaleString('zh-CN')}
                                            </div>
                                        </div>
                                    </div>
                                </List.Item>
                            );
                        }}
                    />
                )}
            </Drawer>
        </ConfigProvider>
    );
}
