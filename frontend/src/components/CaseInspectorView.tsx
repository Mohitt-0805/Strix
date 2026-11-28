import React from 'react';
import { RunInspectorView, RunInspectorViewProps } from './RunInspectorView';

export { RunInspectorView };
export type { RunInspectorViewProps };

export const CaseInspectorView: React.FC<RunInspectorViewProps> = (props) => {
  return <RunInspectorView {...props} />;
};
