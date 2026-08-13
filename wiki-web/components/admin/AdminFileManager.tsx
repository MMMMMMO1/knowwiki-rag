'use client';

import { useState, useEffect, useCallback } from 'react';
import { Tree, Button, Alert, Typography, Tooltip, Modal, Tag, Spin, Empty, Input, message } from 'antd';
import type { TreeDataNode } from 'antd';
import {
    DeleteOutlined, FolderOutlined, FileTextOutlined,
    CheckCircleOutlined, ReloadOutlined, FolderAddOutlined, SyncOutlined
} from '@ant-design/icons';
import type { TreeFolder, TreeFile } from '@/types';

import Uppy from '@uppy/core';
import type { UploadResult, Meta } from '@uppy/core';
import Dashboard from '@uppy/react/dashboard';
import XHRUpload from '@uppy/xhr-upload';
import '@uppy/core/css/style.min.css';
import '@uppy/dashboard/css/style.min.css';
import { redirectToLoginAfterAuthExpired } from '@/lib/auth-token';

const { Text } = Typography;
const MAX_UPLOAD_FILES = 20;
const UPLOAD_CONCURRENCY = 3;

interface AdminFileManagerProps {
    token: string;
    onTreeChange: () => void;
}

interface OperationResult {
    success: boolean;
    message: string;
}

interface UploadProxyResponse extends Record<string, unknown> {
    success?: boolean;
    message?: string;
}

/* ─── Build Ant Design TreeDataNode from backend's folder/file structure ─── */

interface ExtendedTreeDataNode extends TreeDataNode {
    isFolder: boolean;
    nodeId: number;
    itemType: 'folder' | 'file';
}

function buildAntTree(items: (TreeFolder | TreeFile)[]): ExtendedTreeDataNode[] {
    const result: ExtendedTreeDataNode[] = [];

    const sorted = [...items].sort((a, b) => a.sort_order - b.sort_order);

    for (const item of sorted) {
        if ('files' in item) {
            const folder = item as TreeFolder;
            const childNodes = buildAntTree(folder.children || []);
            const fileNodes: ExtendedTreeDataNode[] = (folder.files || [])
                .sort((a, b) => a.sort_order - b.sort_order)
                .map((file) => ({
                    key: `file-${file.id}`,
                    title: file.title,
                    icon: <FileTextOutlined style={{ color: '#1677ff' }} />,
                    isLeaf: true,
                    isFolder: false,
                    nodeId: file.id,
                    itemType: 'file' as const,
                }));

            result.push({
                key: `folder-${folder.id}`,
                title: folder.title,
                icon: <FolderOutlined style={{ color: '#faad14' }} />,
                isLeaf: false,
                isFolder: true,
                nodeId: folder.id,
                itemType: 'folder' as const,
                children: [...childNodes, ...fileNodes],
            });
        } else {
            const file = item as TreeFile;
            result.push({
                key: `file-${file.id}`,
                title: file.title,
                icon: <FileTextOutlined style={{ color: '#1677ff' }} />,
                isLeaf: true,
                isFolder: false,
                nodeId: file.id,
                itemType: 'file' as const,
            });
        }
    }

    return result;
}

/* ─── Component ─── */

export function AdminFileManager({ token, onTreeChange }: AdminFileManagerProps) {
    const [treeData, setTreeData] = useState<(TreeFolder | TreeFile)[]>([]);
    const [loading, setLoading] = useState(true);
    const [selectedFolderId, setSelectedFolderId] = useState<number | null>(null);
    const [selectedFolderTitle, setSelectedFolderTitle] = useState<string>('根目录');
    const [deletingKey, setDeletingKey] = useState<string | null>(null);
    const [result, setResult] = useState<OperationResult | null>(null);
    const [syncStatus, setSyncStatus] = useState<{
        success: boolean;
        pending_upload: number;
        pending_delete: number;
        processing: number;
        failed: number;
        synced: number;
        deleted: number;
        latest_error?: string | null;
    } | null>(null);
    const [syncStatusLoading, setSyncStatusLoading] = useState(false);
    const [syncRetrying, setSyncRetrying] = useState(false);

    const [isCreateModalVisible, setIsCreateModalVisible] = useState(false);
    const [newFolderName, setNewFolderName] = useState('');
    const [isCreatingFolder, setIsCreatingFolder] = useState(false);

    /* ── Uppy 上传实例 ── */
    const [uppy] = useState(() => {
        const instance = new Uppy<Meta, UploadProxyResponse>({
            restrictions: {
                allowedFileTypes: ['.md', '.html', '.docx', '.txt', '.pdf'],
                maxNumberOfFiles: MAX_UPLOAD_FILES,
            },
            autoProceed: false,
        });
        return instance;
    });

    /* ── 管理员 Token 变化时重新配置 Uppy 上传插件 ── */
    useEffect(() => {
        // 先移除旧插件，避免 React 严格模式或 Token 刷新后重复注册上传器。
        const existingPlugin = uppy.getPlugin('XHRUpload');
        if (existingPlugin) {
            uppy.removePlugin(existingPlugin);
        }

        uppy.use(XHRUpload, {
            endpoint: '/api/admin/upload',
            fieldName: 'file',
            headers: {
                'Authorization': `Bearer ${token}`,
            },
            formData: true,
            allowedMetaFields: ['folder_id'],
            // 说明：每个文件仍走独立后端上传接口，这里只控制浏览器侧并发请求数量，避免一次性压满后端和 S3。
            limit: UPLOAD_CONCURRENCY,
        });
    }, [uppy, token]);

    useEffect(() => {
        // Uppy 只提交 Wiki 目录 ID；知识库同步由后端统一处理。
        uppy.setMeta({
            folder_id: selectedFolderId !== null ? String(selectedFolderId) : '',
        });
    }, [uppy, selectedFolderId]);

    const [isMounted, setIsMounted] = useState(false);
    useEffect(() => {
        setIsMounted(true);
    }, []);

    const fetchSyncStatus = useCallback(async () => {
        try {
            setSyncStatusLoading(true);
            const res = await fetch('/api/admin/knowledge/status', {
                headers: { 'Authorization': `Bearer ${token}` },
            });
            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.message || '获取知识库状态失败');
            }
            setSyncStatus(data);
        } catch (error) {
            console.error('Fetch knowledge sync status error:', error);
            setSyncStatus(null);
        } finally {
            setSyncStatusLoading(false);
        }
    }, [token]);

    const triggerSync = async () => {
        try {
            setSyncRetrying(true);
            const res = await fetch('/api/admin/knowledge/sync', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` },
            });
            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.message || '触发知识库同步失败');
            }
            message.success('已触发知识库同步');
            await fetchSyncStatus();
        } catch (error) {
            message.error(error instanceof Error ? error.message : '触发知识库同步失败');
        } finally {
            setSyncRetrying(false);
        }
    };

    useEffect(() => {
        fetchSyncStatus();
    }, [fetchSyncStatus]);

    useEffect(() => {
        const hasPendingSync = Boolean(syncStatus && (
            syncStatus.pending_upload > 0
            || syncStatus.pending_delete > 0
            || syncStatus.processing > 0
        ));
        if (!hasPendingSync) return;

        // 知识库同步在上传后需要索引和嵌入处理；存在待处理任务时自动轮询状态。
        const timer = window.setInterval(fetchSyncStatus, 5000);
        return () => window.clearInterval(timer);
    }, [fetchSyncStatus, syncStatus]);

    /* ── Fetch tree ── */
    const fetchTree = useCallback(async () => {
        try {
            setLoading(true);
            // 说明：目录树通过 Next.js API Route 代理到后端，避免线上环境依赖固定的 /wiki-api rewrite。
            const res = await fetch(`/api/nodes/tree`, {
                cache: 'no-store',
                headers: { 'Authorization': `Bearer ${token}` },
            });
            if (!res.ok) throw new Error('Failed to fetch tree data');
            const data = await res.json();
            setTreeData(data);
        } catch (error) {
            console.error('Fetch tree error:', error);
            setResult({ success: false, message: '检索目录失败，请检查后端设置。' });
        } finally {
            setLoading(false);
        }
    }, [token]);

    const handleCreateFolder = async () => {
        if (!newFolderName.trim()) {
            message.warning('请输入文件夹名称');
            return;
        }
        try {
            setIsCreatingFolder(true);
            // 说明：新建文件夹也走 Next.js 代理，和上传、删除保持同一个后端地址来源。
            const res = await fetch(`/api/admin/folder`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({
                    title: newFolderName.trim(),
                    parent_id: selectedFolderId
                })
            });
            if (!res.ok) {
                const errorData = await res.json().catch(() => null);
                throw new Error(errorData?.detail || '创建文件夹失败');
            }
            message.success('创建文件夹成功');
            setIsCreateModalVisible(false);
            setNewFolderName('');
            fetchTree();
            onTreeChange();
        } catch (error) {
            message.error(error instanceof Error ? error.message : '创建文件夹失败');
        } finally {
            setIsCreatingFolder(false);
        }
    };

    useEffect(() => { fetchTree(); }, [fetchTree]);

    /* ── Uppy events ── */
    useEffect(() => {
        const onComplete = (uploadResult: UploadResult<Meta, UploadProxyResponse>) => {
            const successful = uploadResult.successful || [];
            const failed = uploadResult.failed || [];
            const firstSuccessBody = successful[0]?.response?.body;
            const firstFailedBody = failed[0]?.response?.body;
            const hasUnauthorizedFailure = failed.some((item) => item.response?.status === 401);

            if (hasUnauthorizedFailure) {
                redirectToLoginAfterAuthExpired();
                return;
            }

            if (successful.length > 0) {
                setResult({
                    success: true,
                    message: successful.length === 1
                        ? firstSuccessBody?.message || '成功上传 1 个文件'
                        : `成功上传 ${successful.length} 个文件`,
                });
                fetchTree();
                fetchSyncStatus();
                onTreeChange();
                // 上传完成后稍作停留，让用户能看到成功状态，再清空待上传列表。
                setTimeout(() => {
                    uppy.clear();
                }, 1500);
            }
            if (failed.length > 0) {
                setResult({
                    success: false,
                    message: firstFailedBody?.message || `${failed.length} 个文件上传失败`,
                });
                fetchTree();
                fetchSyncStatus();
                onTreeChange();
            }
        };

        uppy.on('complete', onComplete);

        return () => {
            uppy.off('complete', onComplete);
        };
    }, [uppy, onTreeChange, fetchTree, fetchSyncStatus]);

    /* ── Cleanup Uppy on unmount ── */
    // Removed uppy.destroy() here to prevent React 18 Strict Mode from permanently destroying 
    // the Uppy instance on its initial double-render hook, which caused the blank box bug.

    /* ── Delete handler ── */
    const handleDelete = (nodeId: number, title: string, itemType: 'folder' | 'file') => {
        Modal.confirm({
            title: '确认删除',
            content: `确认要删除 "${title}"？${itemType === 'folder' ? '文件夹下所有内容也将被删除。' : ''}此操作不可撤销。`,
            okText: '删除',
            cancelText: '取消',
            okButtonProps: { danger: true },
            onOk: async () => {
                const key = `${itemType}-${nodeId}`;
                setDeletingKey(key);
                setResult(null);
                try {
                    const res = await fetch(
                        `/api/admin/delete/${nodeId}?item_type=${itemType}&delete_physical=true`,
                        {
                            method: 'DELETE',
                            headers: { 'Authorization': `Bearer ${token}` },
                        }
                    );
                    const data = await res.json();
                    setResult(data);
                    if (data.success) {
                        // If deleted folder was the selected upload target, reset to root
                        if (itemType === 'folder' && selectedFolderId === nodeId) {
                            setSelectedFolderId(null);
                            setSelectedFolderTitle('根目录');
                        }
                        await fetchTree();
                        await fetchSyncStatus();
                        onTreeChange();
                    }
                } catch {
                    setResult({ success: false, message: '删除失败，请重试' });
                } finally {
                    setDeletingKey(null);
                }
            },
        });
    };

    /* ── Tree select handler ── */
    const handleTreeSelect = (_selectedKeys: React.Key[], info: { node: TreeDataNode }) => {
        const node = info.node as ExtendedTreeDataNode;
        if (node.isFolder) {
            setSelectedFolderId(node.nodeId);
            setSelectedFolderTitle(node.title as string);
            // Update Uppy metadata
            uppy.setMeta({ folder_id: String(node.nodeId) });
        }
    };

    const antTreeData = buildAntTree(treeData);
    const pendingCount = syncStatus ? syncStatus.pending_upload + syncStatus.pending_delete : 0;
    const processingCount = syncStatus?.processing ?? 0;
    const syncHealthColor = syncStatus?.failed
        ? 'error'
        : pendingCount > 0 || processingCount > 0
            ? 'processing'
            : 'success';
    const syncHealthText = syncStatus?.failed
        ? '同步异常'
        : pendingCount > 0 || processingCount > 0
            ? '缓存处理中'
            : '已同步';

    return (
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
            <div style={{
                flex: '1 1 100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 12,
                flexWrap: 'wrap',
                padding: '12px 14px',
                background: '#f8faf8',
                border: '1px solid rgba(197,197,217,0.2)',
                borderRadius: 12,
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <SyncOutlined spin={Boolean(syncStatusLoading || pendingCount > 0 || processingCount > 0)} style={{ color: '#cc785c' }} />
                    <Text strong style={{ fontSize: 13, color: '#444656', fontFamily: 'Inter, sans-serif' }}>
                        知识库同步
                    </Text>
                    <Tag color={syncHealthColor}>{syncHealthText}</Tag>
                    <Tag color="blue">待上传 {syncStatus?.pending_upload ?? 0}</Tag>
                    <Tag color="cyan">处理中 {syncStatus?.processing ?? 0}</Tag>
                    <Tag color="gold">待删除 {syncStatus?.pending_delete ?? 0}</Tag>
                    <Tag color={syncStatus?.failed ? 'red' : 'default'}>失败 {syncStatus?.failed ?? 0}</Tag>
                    <Tag color="green">已同步 {syncStatus?.synced ?? 0}</Tag>
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                    <Tooltip title="刷新同步状态">
                        <Button
                            type="text"
                            size="small"
                            icon={<ReloadOutlined spin={syncStatusLoading} />}
                            onClick={fetchSyncStatus}
                        />
                    </Tooltip>
                    <Tooltip title="重试待处理和失败任务">
                        <Button
                            type="text"
                            size="small"
                            icon={<ReloadOutlined spin={syncRetrying} />}
                            onClick={triggerSync}
                        />
                    </Tooltip>
                </div>
                {syncStatus?.latest_error && (
                    <Alert
                        type="error"
                        message={syncStatus.latest_error}
                        showIcon
                        style={{ width: '100%', borderRadius: 10 }}
                    />
                )}
            </div>

            {/* Left: Upload */}
            <div style={{ flex: '1 1 340px', minWidth: 300 }}>
                <Text strong style={{
                    fontSize: 13,
                    color: '#444656',
                    fontFamily: 'Inter, sans-serif',
                    display: 'block',
                    marginBottom: 12,
                }}>
                    上传文件
                </Text>

                {/* Upload target indicator */}
                <div style={{ marginBottom: 12 }}>
                    <Text style={{ fontSize: 12, color: '#757688', fontFamily: 'Inter, sans-serif' }}>
                        上传到：
                    </Text>
                    <Tag
                        color={selectedFolderId === null ? 'default' : 'blue'}
                        style={{ marginLeft: 8, borderRadius: 6 }}
                    >
                        <FolderOutlined /> {selectedFolderTitle}
                    </Tag>
                    {selectedFolderId !== null && (
                        <Button
                            type="link"
                            size="small"
                            onClick={() => {
                                setSelectedFolderId(null);
                                setSelectedFolderTitle('根目录');
                                uppy.setMeta({ folder_id: '' });
                            }}
                            style={{ fontSize: 12, padding: '0 4px' }}
                        >
                            重置为根目录
                        </Button>
                    )}
                </div>

                {/* Uppy Dashboard */}
                <div className="uppy-wrapper" style={{ minHeight: 320 }}>
                    {isMounted ? (
                        <Dashboard
                            uppy={uppy}
                            proudlyDisplayPoweredByUppy={false}
                            height={320}
                            width="100%"
                            theme="light"
                            note={`支持 .md、.html、.docx、.txt、.pdf；最多 ${MAX_UPLOAD_FILES} 个文件，并发 ${UPLOAD_CONCURRENCY} 个`}
                        />
                    ) : (
                        <div style={{ height: 320, background: '#f8faf8', borderRadius: 14 }} />
                    )}
                </div>

                {result && (
                    <Alert
                        type={result.success ? 'success' : 'error'}
                        message={result.message}
                        showIcon
                        closable
                        onClose={() => setResult(null)}
                        style={{ marginTop: 12, borderRadius: 10 }}
                    />
                )}
            </div>

            {/* Divider */}
            <div style={{
                width: 1,
                background: 'rgba(197,197,217,0.3)',
                alignSelf: 'stretch',
            }} />

            {/* Right: File Tree */}
            <div style={{ flex: '1 1 340px', minWidth: 300 }}>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    marginBottom: 12,
                }}>
                    <Text strong style={{
                        fontSize: 13,
                        color: '#444656',
                        fontFamily: 'Inter, sans-serif',
                    }}>
                        文件目录（点击文件夹选择上传/新建位置）
                    </Text>
                    <div style={{ display: 'flex', gap: 4 }}>
                        <Tooltip title="新建文件夹">
                            <Button
                                type="text"
                                size="small"
                                icon={<FolderAddOutlined />}
                                onClick={() => setIsCreateModalVisible(true)}
                            />
                        </Tooltip>
                        <Tooltip title="刷新">
                            <Button
                                type="text"
                                size="small"
                                icon={<ReloadOutlined spin={loading} />}
                                onClick={fetchTree}
                            />
                        </Tooltip>
                    </div>
                </div>

                {loading ? (
                    <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
                ) : antTreeData.length === 0 ? (
                    <Empty
                        description="暂无文件"
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        style={{ padding: 32 }}
                    />
                ) : (
                    <div style={{
                        maxHeight: 420,
                        overflowY: 'auto',
                        background: '#f8faf8',
                        borderRadius: 12,
                        border: '1px solid rgba(197,197,217,0.2)',
                        padding: 8,
                    }}>
                        {/* Root folder selector */}
                        <div
                            onClick={() => {
                                setSelectedFolderId(null);
                                setSelectedFolderTitle('根目录');
                                uppy.setMeta({ folder_id: '' });
                            }}
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 8,
                                padding: '6px 12px',
                                borderRadius: 8,
                                cursor: 'pointer',
                                background: selectedFolderId === null ? '#e8ecff' : 'transparent',
                                marginBottom: 4,
                                transition: 'background 0.15s',
                            }}
                        >
                            <FolderOutlined style={{ color: '#faad14' }} />
                            <span style={{ fontSize: 13, fontFamily: 'Inter, sans-serif', flex: 1 }}>
                                根目录
                            </span>
                            {selectedFolderId === null && (
                                <CheckCircleOutlined style={{ color: '#cc785c', fontSize: 12 }} />
                            )}
                        </div>

                        <Tree
                            treeData={antTreeData}
                            showIcon
                            blockNode
                            defaultExpandAll
                            onSelect={handleTreeSelect}
                            titleRender={(node) => {
                                const extNode = node as ExtendedTreeDataNode;
                                return (
                                    <div style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'space-between',
                                        width: '100%',
                                        gap: 8,
                                    }}>
                                        <span style={{
                                            fontSize: 13,
                                            fontFamily: 'Inter, sans-serif',
                                            color: extNode.isFolder ? '#181d1a' : '#757688',
                                            flex: 1,
                                        }}>
                                            {extNode.title as string}
                                            {extNode.isFolder && selectedFolderId === extNode.nodeId && (
                                                <CheckCircleOutlined
                                                    style={{ marginLeft: 8, color: '#cc785c', fontSize: 12 }}
                                                />
                                            )}
                                        </span>
                                        <Tooltip title="删除">
                                            <Button
                                                type="text"
                                                size="small"
                                                danger
                                                icon={
                                                    deletingKey === `${extNode.itemType}-${extNode.nodeId}`
                                                        ? <Spin size="small" />
                                                        : <DeleteOutlined />
                                                }
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    handleDelete(
                                                        extNode.nodeId,
                                                        extNode.title as string,
                                                        extNode.itemType
                                                    );
                                                }}
                                                style={{ opacity: 0.6 }}
                                                onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                                                onMouseLeave={(e) => (e.currentTarget.style.opacity = '0.6')}
                                            />
                                        </Tooltip>
                                    </div>
                                );
                            }}
                            style={{ background: 'transparent', fontFamily: 'Inter, sans-serif' }}
                        />
                    </div>
                )}
            </div>

            <Modal
                title="新建文件夹"
                open={isCreateModalVisible}
                onOk={handleCreateFolder}
                onCancel={() => {
                    setIsCreateModalVisible(false);
                    setNewFolderName('');
                }}
                confirmLoading={isCreatingFolder}
                okText="创建"
                cancelText="取消"
            >
                <div style={{ marginBottom: 12 }}>
                    位置: <strong>{selectedFolderTitle}</strong>
                </div>
                <Input
                    placeholder="请输入新文件夹名称"
                    value={newFolderName}
                    onChange={(e) => setNewFolderName(e.target.value)}
                    onPressEnter={handleCreateFolder}
                    autoFocus
                />
            </Modal>
        </div>
    );
}
