import React, { useState, useRef, useCallback, forwardRef, useImperativeHandle } from 'react';
import Editor from '@monaco-editor/react';
import yaml from 'js-yaml';

/**
 * ResourceEditor — Monaco-based code editor with YAML/JSON toggle.
 *
 * Props:
 *   value        — initial content string
 *   onChange     — callback when content changes
 *   onSubmit     — callback for submit action
 *   onCancel     — callback for cancel action
 *   readOnly     — boolean (default false)
 *
 * Exposed via ref:
 *   getValue()   — returns current editor content
 *   isValid()    — returns true if no syntax errors
 */
const ResourceEditor = forwardRef(function ResourceEditor(
  { value = '', onChange, onSubmit, onCancel, readOnly = false },
  ref
) {
  const [language, setLanguage] = useState('json');
  const [content, setContent] = useState(value);
  const [markers, setMarkers] = useState([]);
  const editorRef = useRef(null);

  const hasErrors = markers.length > 0;

  // Expose getValue and isValid to parent via ref
  useImperativeHandle(ref, () => ({
    getValue: () => content,
    isValid: () => markers.length === 0,
  }));

  const handleEditorDidMount = (editor) => {
    editorRef.current = editor;
  };

  const handleEditorChange = useCallback(
    (newValue) => {
      setContent(newValue || '');
      if (onChange) {
        onChange(newValue || '');
      }
    },
    [onChange]
  );

  const handleValidation = useCallback((newMarkers) => {
    // Filter to only error-level markers (severity 8 = Error in Monaco)
    const errors = newMarkers.filter((m) => m.severity >= 8);
    setMarkers(errors);
  }, []);

  /**
   * Convert content between JSON and YAML.
   * If conversion fails, switch language mode without converting content.
   */
  const convertToJson = (yamlContent) => {
    try {
      const parsed = yaml.load(yamlContent);
      return JSON.stringify(parsed, null, 2);
    } catch {
      return null;
    }
  };

  const convertToYaml = (jsonContent) => {
    try {
      const parsed = JSON.parse(jsonContent);
      return yaml.dump(parsed, { indent: 2, lineWidth: -1 });
    } catch {
      return null;
    }
  };

  const handleToggleLanguage = () => {
    if (language === 'json') {
      // Switch to YAML
      const converted = convertToYaml(content);
      if (converted !== null) {
        setContent(converted);
        if (onChange) onChange(converted);
      }
      setLanguage('yaml');
    } else {
      // Switch to JSON
      const converted = convertToJson(content);
      if (converted !== null) {
        setContent(converted);
        if (onChange) onChange(converted);
      }
      setLanguage('json');
    }
  };

  return (
    <div className="flex flex-col border border-gray-300 rounded-lg overflow-hidden bg-white h-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-50 border-b border-gray-200">
        <div className="flex items-center gap-2">
          {/* Language toggle */}
          <button
            type="button"
            onClick={handleToggleLanguage}
            disabled={readOnly}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 bg-white text-gray-700 hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            aria-label={`Switch to ${language === 'json' ? 'YAML' : 'JSON'} mode`}
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
            </svg>
            {language === 'json' ? 'Switch to YAML' : 'Switch to JSON'}
          </button>

          {/* Current mode indicator */}
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-indigo-100 text-indigo-800">
            {language.toUpperCase()}
          </span>

          {/* Error indicator */}
          {hasErrors && (
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800">
              {markers.length} {markers.length === 1 ? 'error' : 'errors'}
            </span>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-2">
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              className="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 bg-white text-gray-700 hover:bg-gray-100 transition-colors"
            >
              Cancel
            </button>
          )}
          {onSubmit && (
            <button
              type="button"
              onClick={onSubmit}
              disabled={hasErrors || readOnly}
              className="px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Submit
            </button>
          )}
        </div>
      </div>

      {/* Monaco Editor */}
      <div className="flex-1 min-h-0">
        <Editor
          height="100%"
          language={language}
          value={content}
          onChange={handleEditorChange}
          onMount={handleEditorDidMount}
          onValidate={handleValidation}
          options={{
            readOnly,
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 2,
            wordWrap: 'on',
            formatOnPaste: true,
          }}
          theme="vs-dark"
        />
      </div>
    </div>
  );
});

export default ResourceEditor;
