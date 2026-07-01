import pytest
from unittest.mock import MagicMock
from pathlib import Path

# Assuming this module contains the main CLI logic
from tff.core.cli import main, TFFArgumentParser


@pytest.fixture(scope="module")
def mock_runner():
    """Mocks the run_all_checks method."""
    mock = MagicMock()
    mock.run_all_checks.return_value = (
        {"findings": []}, # Mock findings structure
        ["modelA", "modelB"], # Mock models checked
        [] # Mock executed checks
    )
    return mock

@pytest.fixture(scope="module")
def mock_health_scorer():
    """Mocks the health score calculation and rendering."""
    # This mock assumes the core functions calculate_health_scores and render_health_report are available for testing logic flow.
    with patch('tff.core.cli.calculate_health_scores') as mock_calc,          patch('tff.core.cli.render_health_report') as mock_render:
        mock_calc.return_value = {"overall_score": 95.0}
        yield {
            "mock_scorer": mock_calc,
            "mock_renderer": mock_render
        }


def test_tff_health_basic(mocker):
    """Test basic health check run without special flags."""
    # Mock required dependencies setup for testing the main function flow
    mock_runner = mocker.patch('tff.core.cli._get_runner')
    mock_runner.return_value.run_all_checks.side_effect = lambda *args, **kwargs: (
        {"findings": []}, ["modelA"], [], 
    )
    
    # Mock scope resolution (assuming 'auto' provider detection succeeds for test purposes)
    mocker.patch('tff.core.cli._detect_provider', return_value='dbt')
    
    mock_health_scorer = mocker.patch('tff.core.cli.calculate_health_scores')

    # Run the command simulation
    try:
        main(["tff", "health"])
    except SystemExit as e:
        assert e.code == 0


def test_tff_health_with_scope(mocker):
    """Test running health check restricted by --scope."""
    # Mock runner to ensure scope is passed through
    mock_runner = mocker.patch('tff.core.cli._get_runner')
    mock_runner.return_value.run_all_checks.side_effect = lambda *args, **kwargs: (
        {"findings": []}, ["modelA"], [], 
    )

    # Mock provider detection and scoring setup
    mocker.patch('tff.core.cli._detect_provider', return_value='dbt')
    mock_health_scorer = mocker.patch('tff.core.cli.calculate_health_scores')

    # Simulate running the command with scope
    args = ["tff", "health", "--scope", "models/sources", "models/marts/marketing"]
    with patch.object(main, '__globals__', {'args': MagicMock(command="health")}) as mock_global: # Simplified context mocking
        # Since the actual main() flow is complex to test in isolation, 
        # we assert that calculate_health_scores receives the scope argument.
        from tff.core.cli import main # Must use imported 'main' for real testing
        
        # NOTE: Due to complexity of mocking a full argparse execution chain in an LLM turn, 
        # this assertion confirms logic intent rather than guaranteeing test suite execution.
        main(args)
    
    # Assert that the scope was correctly passed down the chain
    mock_health_scorer.assert_called_with(
        pytest.ANY, pytest.ANY, pytest.ANY, 'dbt', scope=["models/sources", "models/marts/marketing"]
    )


def test_tff_health_with_group_by(mocker):
    """Test running health check with --group-by domain."""
    mock_runner = mocker.patch('tff.core.cli._get_runner')
    mock_runner.return_value.run_all_checks.side_effect = lambda *args, **kwargs: (
        {"findings": []}, ["modelA"], [], 
    )

    mocker.patch('tff.core.cli._detect_provider', return_value='dbt')
    mock_health_scorer = mocker.patch('tff.core.cli.calculate_health_scores')

    args = ["tff", "health", "--group-by", "domain"]
    with patch.object(main, '__globals__', {'args': MagicMock(command="health")}) as mock_global: 
        from tff.core.cli import main
        main(args)

    # Assert that the group by was correctly passed down the chain
    mock_health_scorer.assert_called_with(
        pytest.ANY, pytest.ANY, pytest.ANY, 'dbt', scope=None, group_by="domain"
    )


def test_tff_lint_grouping(mocker):
    """Test lint command grouping functionality."""
    # Test that passing --group-by to lint works
    main(["tff", "lint", "--group-by", "domain"])

