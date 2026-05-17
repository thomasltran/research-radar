import React, { useState } from 'react';
import { Folder, Plus, Trash2, X } from 'lucide-react';
import type { PaperFolder } from '../../types';
import { ConfirmModal } from '../ui/ConfirmModal';

export function ProjectPanel(props: {
  folders: PaperFolder[];
  selectedFolderId: number | null;
  newFolderName: string;
  onSelectFolder: (id: number | null) => void;
  onSetNewFolderName: (value: string) => void;
  onCreateFolder: (event: React.FormEvent<HTMLFormElement>) => void;
  onDeleteFolder: (id: number) => void;
}) {
  const [pendingDelete, setPendingDelete] = useState<PaperFolder | null>(null);
  return (
    <div className="project-panel">
      <div className="filter-header">
        <div className="filter-header-left">
          <span>Projects</span>
          {props.folders.length > 0 && (
            props.selectedFolderId !== null ? (
              <button className="count-clear" onClick={() => props.onSelectFolder(null)} aria-label="Clear project">
                <span>{props.folders.length}</span>
                <X size={11} />
              </button>
            ) : <strong>{props.folders.length}</strong>
          )}
        </div>
      </div>
      <div className="project-list">
        {props.folders.map((folder) => (
          <div className={props.selectedFolderId === folder.id ? 'project-row active' : 'project-row'} key={folder.id}>
            <button
              className="project-button"
              onClick={() => props.onSelectFolder(props.selectedFolderId === folder.id ? null : folder.id)}
              aria-pressed={props.selectedFolderId === folder.id}
              title={`${folder.paper_count ?? 0} papers`}
            >
              <Folder size={15} />
              <span>{folder.name}</span>
              <strong>{folder.paper_count ?? 0}</strong>
            </button>
            <button
              className="project-delete"
              onClick={() => setPendingDelete(folder)}
              aria-label={`Delete ${folder.name}`}
              title={`Delete ${folder.name}`}
            >
              <Trash2 size={13} />
            </button>
          </div>
        ))}
      </div>
      <form className="project-create" onSubmit={props.onCreateFolder}>
        <input
          value={props.newFolderName}
          onChange={(event) => props.onSetNewFolderName(event.target.value)}
          placeholder="Add project"
          aria-label="New project name"
        />
        <button className="ghost-button icon-button" type="submit" aria-label="Create project">
          <Plus size={14} />
        </button>
      </form>
      {pendingDelete && (
        <ConfirmModal
          title="Delete project?"
          body={`This removes "${pendingDelete.name}" and its paper memberships. Papers stay in your library.`}
          confirmLabel="Delete"
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => {
            props.onDeleteFolder(pendingDelete.id);
            setPendingDelete(null);
          }}
        />
      )}
    </div>
  );
}
