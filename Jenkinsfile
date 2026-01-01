pipeline {
  agent any

  options {
    // Keep builds for 30 days
    buildDiscarder(logRotator(daysToKeepStr: '30'))
  }

  stages {
    stage('Build') {
      steps {
        script {
          // Set status to pending at the start
          setGitHubCommitStatus('Jenkins', 'PENDING', 'Build in progress')
        }
        echo 'Building..'
      }
    }
    stage('Test') {
      steps {
        script {
          setGitHubCommitStatus('Jenkins', 'PENDING', 'Running tests')
        }
        echo 'Testing..'
      }
    }
    stage('Deploy') {
      steps {
        script {
          setGitHubCommitStatus('Jenkins', 'PENDING', 'Deploying')
        }
        echo 'Deploying....'
      }
    }
  }

  post {
    success {
      script {
        setGitHubCommitStatus('Jenkins', 'SUCCESS', 'Build succeeded')
      }
    }
    failure {
      script {
        setGitHubCommitStatus('Jenkins', 'FAILURE', 'Build failed')
      }
    }
    unstable {
      script {
        setGitHubCommitStatus('Jenkins', 'FAILURE', 'Build unstable')
      }
    }
    aborted {
      script {
        setGitHubCommitStatus('Jenkins', 'ERROR', 'Build aborted')
      }
    }
  }
}

def setGitHubCommitStatus(String context, String state, String description) {
  // Requires the GitHub plugin to be installed
  // Set up GitHub credentials in Jenkins with ID 'github-credentials'
  step([
    $class: 'GitHubCommitStatusSetter',
    contextSource: [$class: 'ManuallyEnteredCommitContextSource', context: context],
    statusResultSource: [
      $class: 'ConditionalStatusResultSource',
      results: [
        [$class: 'AnyBuildResult', message: description, state: state]
      ]
    ],
    errorHandlers: [[$class: 'ShallowAnyErrorHandler']]
  ])
}
