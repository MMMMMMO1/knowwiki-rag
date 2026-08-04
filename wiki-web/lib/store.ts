import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface WikiStore {
    isSidebarCollapsed: boolean;
    fontSize: 'base' | 'lg' | 'xl';
    theme: string;
    toggleSidebar: () => void;
    setFontSize: (size: 'base' | 'lg' | 'xl') => void;
    setTheme: (theme: string) => void;
}

export const useWikiStore = create<WikiStore>()(
    persist(
        (set) => ({
            isSidebarCollapsed: false,
            fontSize: 'base',
            theme: 'light',
            toggleSidebar: () => set((state) => ({ isSidebarCollapsed: !state.isSidebarCollapsed })),
            setFontSize: (size) => set({ fontSize: size }),
            setTheme: (theme) => set({ theme }),
        }),
        {
            name: 'wiki-storage',
        }
    )
);
